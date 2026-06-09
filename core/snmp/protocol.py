"""
پیاده‌سازی دستی SNMPv1 و v2c بدون وابستگی خارجی:
- encode_oid / encode_length
- build_snmp_get_v1, build_snmp_get_v2c
- parse_snmp_response
- کش نسخه SNMP برای هر IP (تشخیص خودکار SNMPv1/v2c)
- snmp_get (نسخه‌ای)
- snmp_get_with_fallback (با کش و تست هوشمند)
- snmp_get_bulk
"""

import socket
import threading
import logging
import time

log = logging.getLogger("PrinterMonitor")

SNMP_ERROR_NAMES = {
    0: "noError", 1: "tooBig", 2: "noSuchName", 3: "badValue",
    4: "readOnly", 5: "genErr", 6: "noAccess", 7: "wrongType",
    8: "wrongLength", 9: "wrongEncoding", 10: "wrongValue", 11: "noCreation",
    12: "inconsistentValue", 13: "resourceUnavailable", 14: "commitFailed",
    15: "undoFailed", 16: "authorizationError", 17: "notWritable", 18: "inconsistentName"
}

# ─── کش نسخه SNMP برای هر IP/community ────────────────────────────
# هر ورودی به شکل زیر ذخیره می‌شود:
#   {"version": 1|2|None, "expires_at": monotonic_ts|None}
# برای نسخه‌های ناموفق (offline / timeout) negative-cache با TTL کوتاه نگه می‌داریم
# تا در هر pull دوباره probe نشود.
_SNMP_VERSION_CACHE = {}
_version_cache_lock = threading.Lock()
_NEGATIVE_CACHE_TTL = 30.0
_POSITIVE_CACHE_TTL = 3600.0


def _version_cache_key(ip: str, community: str) -> str:
    return f"{ip}|{community}"



def _get_cached_version(ip: str, community: str):
    key = _version_cache_key(ip, community)
    with _version_cache_lock:
        entry = _SNMP_VERSION_CACHE.get(key)
        if entry is None and ip in _SNMP_VERSION_CACHE:
            # backward compatibility با کش‌های قدیمی فقط بر پایه IP
            legacy = _SNMP_VERSION_CACHE.get(ip)
            if legacy in (1, 2, None):
                entry = {"version": legacy, "expires_at": None if legacy in (1, 2) else time.monotonic() + _NEGATIVE_CACHE_TTL}
                _SNMP_VERSION_CACHE[key] = entry
                _SNMP_VERSION_CACHE.pop(ip, None)
        if not isinstance(entry, dict):
            return False, None
        expires_at = entry.get("expires_at")
        if expires_at is not None and time.monotonic() >= expires_at:
            _SNMP_VERSION_CACHE.pop(key, None)
            return False, None
        return True, entry.get("version")



def _set_cached_version(ip: str, community: str, version: int | None, ttl: float | None):
    key = _version_cache_key(ip, community)
    with _version_cache_lock:
        _SNMP_VERSION_CACHE[key] = {
            "version": version,
            "expires_at": (time.monotonic() + ttl) if ttl is not None else None,
        }



def _clear_cached_version(ip: str, community: str):
    key = _version_cache_key(ip, community)
    with _version_cache_lock:
        _SNMP_VERSION_CACHE.pop(key, None)
        _SNMP_VERSION_CACHE.pop(ip, None)



def _detect_snmp_version(ip: str, community: str, port: int = 161, probe_timeout: float = 1.5) -> int | None:
    """
    تشخیص نسخه SNMP با تست sysUptime (1.3.6.1.2.1.1.3.0).
    ابتدا v1 را تست می‌کند (چون رایج‌تر است)، سپس v2c.
    نتیجه در cache ذخیره می‌شود؛ برای عدم پاسخ نیز negative-cache کوتاه نگه می‌داریم.
    """
    found, cached_version = _get_cached_version(ip, community)
    if found:
        return cached_version

    probe_oid = "1.3.6.1.2.1.1.3.0"

    # 🔥 تغییر: اول v1 تست می‌شود (چون در شبکه‌های واقعی رایج‌تر است)
    res_v1 = snmp_get(ip, probe_oid, community, port, probe_timeout, version=1)
    if res_v1 is not None:
        _set_cached_version(ip, community, 1, _POSITIVE_CACHE_TTL)
        log.debug(f"SNMP cache: {ip} -> v1")
        return 1

    # تست v2c
    res_v2 = snmp_get(ip, probe_oid, community, port, probe_timeout, version=2)
    if res_v2 is not None:
        _set_cached_version(ip, community, 2, _POSITIVE_CACHE_TTL)
        log.info(f"SNMP cache: {ip} -> v2c (v1 failed)")
        return 2

    # هیچ‌یک پاسخ ندادند؛ احتمالاً دستگاه آفلاین یا SNMP مسدود است.
    log.debug(f"SNMP cache: {ip} unreachable (both versions failed, cached for {_NEGATIVE_CACHE_TTL:.0f}s)")
    _set_cached_version(ip, community, None, _NEGATIVE_CACHE_TTL)
    return None


# ─── توابع کدگذاری/کدگشایی SNMP (بدون تغییر) ──────────────────────────
def encode_oid(oid_str: str) -> bytes:
    parts = [int(x) for x in oid_str.strip(".").split(".")]
    encoded = [40 * parts[0] + parts[1]]
    for part in parts[2:]:
        if part == 0:
            encoded.append(0)
        else:
            subids = []
            while part > 0:
                subids.append(part & 0x7F)
                part >>= 7
            subids.reverse()
            for i, s in enumerate(subids):
                encoded.append(s | 0x80 if i < len(subids) - 1 else s)
    return bytes(encoded)


def encode_length(n: int) -> bytes:
    if n < 128:
        return bytes([n])
    elif n < 256:
        return bytes([0x81, n])
    else:
        return bytes([0x82, (n >> 8) & 0xFF, n & 0xFF])


def build_snmp_get_v1(community: str, oid: str, request_id: int = 1) -> bytes:
    ob = encode_oid(oid)
    oid_tlv = b'\x06' + encode_length(len(ob)) + ob
    vb = b'\x30' + encode_length(len(oid_tlv) + 2) + oid_tlv + b'\x05\x00'
    vbl = b'\x30' + encode_length(len(vb)) + vb
    rid = request_id & 0x7FFFFFFF
    rb = rid.to_bytes((rid.bit_length() + 8) // 8, 'big')
    rid_tlv = b'\x02' + encode_length(len(rb)) + rb
    pdu_body = rid_tlv + b'\x02\x01\x00\x02\x01\x00' + vbl
    pdu = b'\xa0' + encode_length(len(pdu_body)) + pdu_body
    cb = community.encode()
    comm_tlv = b'\x04' + encode_length(len(cb)) + cb
    msg_body = b'\x02\x01\x00' + comm_tlv + pdu
    return b'\x30' + encode_length(len(msg_body)) + msg_body


def build_snmp_get_v2c(community: str, oid: str, request_id: int = 1) -> bytes:
    ob = encode_oid(oid)
    oid_tlv = b'\x06' + encode_length(len(ob)) + ob
    vb = b'\x30' + encode_length(len(oid_tlv) + 2) + oid_tlv + b'\x05\x00'
    vbl = b'\x30' + encode_length(len(vb)) + vb
    rid = request_id & 0x7FFFFFFF
    rb = rid.to_bytes((rid.bit_length() + 8) // 8, 'big')
    rid_tlv = b'\x02' + encode_length(len(rb)) + rb
    pdu_body = rid_tlv + b'\x02\x01\x00\x02\x01\x00' + vbl
    pdu = b'\xa0' + encode_length(len(pdu_body)) + pdu_body
    cb = community.encode()
    comm_tlv = b'\x04' + encode_length(len(cb)) + cb
    msg_body = b'\x02\x01\x01' + comm_tlv + pdu
    return b'\x30' + encode_length(len(msg_body)) + msg_body


def parse_snmp_response(data: bytes, expected_request_id=None):
    try:
        pos = 0

        def rl(d, p):
            if d[p] & 0x80 == 0:
                return d[p], p + 1
            n = d[p] & 0x7F
            return int.from_bytes(d[p + 1:p + 1 + n], 'big'), p + 1 + n

        assert data[pos] == 0x30
        pos += 1
        _, pos = rl(data, pos)

        pos += 1
        vl, pos = rl(data, pos)
        pos += vl

        pos += 1
        cl, pos = rl(data, pos)
        pos += cl

        assert data[pos] == 0xa2
        pos += 1
        _, pos = rl(data, pos)

        if data[pos] != 0x02:
            return None
        pos += 1
        rid_len, pos = rl(data, pos)
        rid = int.from_bytes(data[pos:pos + rid_len], 'big')
        pos += rid_len
        if expected_request_id is not None and rid != expected_request_id:
            log.debug(f"SNMP req-id mismatch: expected={expected_request_id} got={rid}")
            return None

        if data[pos] != 0x02:
            return None
        pos += 1
        err_len, pos = rl(data, pos)
        error_status = int.from_bytes(data[pos:pos + err_len], 'big')
        pos += err_len
        if error_status != 0:
            log.debug(f"SNMP error-status: {SNMP_ERROR_NAMES.get(error_status, f'err#{error_status}')}")
            return None

        if data[pos] != 0x02:
            return None
        pos += 1
        idx_len, pos = rl(data, pos)
        pos += idx_len

        if data[pos] != 0x30:
            return None
        pos += 1
        _, pos = rl(data, pos)

        if data[pos] != 0x30:
            return None
        pos += 1
        _, pos = rl(data, pos)

        if data[pos] != 0x06:
            return None
        pos += 1
        ol, pos = rl(data, pos)
        pos += ol

        vt = data[pos]
        pos += 1
        vl, pos = rl(data, pos)
        vb = data[pos:pos + vl]

        if vt == 0x02:
            return 0 if vl == 0 else int.from_bytes(vb, 'big', signed=True)
        elif vt == 0x04:
            try:
                return vb.decode('utf-8').strip('\x00').strip()
            except Exception:
                return vb.hex()
        elif vt in (0x41, 0x42, 0x43, 0x44):
            return int.from_bytes(vb, 'big')
        elif vt == 0x40:
            return ".".join(str(b) for b in vb)
        elif vt in (0x80, 0x81, 0x82):
            return None
        return None
    except Exception as e:
        log.debug(f"SNMP parse error: {e}")
        return None


def snmp_get(ip: str, oid: str, community: str = "public",
             port: int = 161, timeout: float = 3.0, request_id: int = 1, version: int = 2):
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        if version == 1:
            pkt = build_snmp_get_v1(community, oid, request_id)
        else:
            pkt = build_snmp_get_v2c(community, oid, request_id)
        s.sendto(pkt, (ip, port))
        resp, _ = s.recvfrom(65535)
        return parse_snmp_response(resp, expected_request_id=request_id)
    except socket.timeout:
        return None
    except Exception as e:
        log.debug(f"snmp_get {ip} {oid} version {version}: {e}")
        return None
    finally:
        if s:
            s.close()


def snmp_get_with_fallback(ip: str, oid: str, community: str = "public",
                           port: int = 161, timeout: float = 3.0, request_id: int = 1,
                           version: int | None = None):
    """
    دریافت SNMP با تشخیص خودکار و کش نسخه.
    ابتدا نسخه مناسب (1 یا 2) را بر اساس تست قبلی یا تست جدید تعیین می‌کند.
    """
    if version in (1, 2):
        return snmp_get(ip, oid, community, port, timeout, request_id, version=version)

    # کش را چک می‌کنیم؛ اگر موجود نبود، تشخیص دهیم (با timeout کوتاه)
    version = _detect_snmp_version(ip, community, port, probe_timeout=1.5)
    # اگر نسخه شناسایی نشد (None) → دستگاه به نظر آفلاین است
    if version is None:
        return None

    # درخواست با نسخه ترجیحی
    result = snmp_get(ip, oid, community, port, timeout, request_id, version=version)
    if result is not None:
        return result

    # اگر نسخه ترجیحی جواب نداد (مثلاً دستگاه ریبوت شده و v1/v2 تغییر کرده)،
    # نسخه دیگر را امتحان کن
    other_version = 2 if version == 1 else 1
    result_other = snmp_get(ip, oid, community, port, timeout, request_id, version=other_version)
    if result_other is not None:
        _set_cached_version(ip, community, other_version, _POSITIVE_CACHE_TTL)
        log.info(f"SNMP cache updated: {ip} -> v{other_version} (v{version} failed)")
        return result_other

    # هر دو نسخه ناموفق → فعلاً negative-cache کوتاه بگذار تا دوباره probe نشود
    _clear_cached_version(ip, community)
    _set_cached_version(ip, community, None, _NEGATIVE_CACHE_TTL)
    return None


def snmp_get_bulk(ip: str, oids: dict, community: str = "public") -> dict:
    """چند OID را یکی‌یکی می‌خواند (sequential GET) با fallback خودکار"""
    result = {}
    for i, (key, oid) in enumerate(oids.items()):
        result[key] = snmp_get_with_fallback(ip, oid, community, request_id=i + 1)
    return result