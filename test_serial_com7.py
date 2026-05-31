import sys
import time

try:
    import serial
except Exception as e:
    print('MISSING_PYSERIAL', e)
    sys.exit(2)

PORT = 'COM7'
BAUD = 9600

print(f'Testing serial port {PORT} @ {BAUD}')
try:
    s = serial.Serial(PORT, BAUD, timeout=3)
except Exception as e:
    print('OPEN_FAILED', e)
    sys.exit(3)

time.sleep(0.2)
try:
    s.write(b'PING\n')
    print('SENT: PING')
    resp = s.readline().decode('utf-8', errors='ignore').strip()
    if resp:
        print('RESPONSE:', resp)
    else:
        print('NO_RESPONSE')
except Exception as e:
    print('WRITE_READ_ERROR', e)
finally:
    try:
        s.close()
    except Exception:
        pass
