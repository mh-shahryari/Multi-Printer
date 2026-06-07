import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config.settings as s
print('DEFAULT:', s.FLASK_PORT)
print('ENV:', os.getenv('FLASK_PORT'))
print('EFFECTIVE:', int(os.getenv('FLASK_PORT', s.FLASK_PORT)))
