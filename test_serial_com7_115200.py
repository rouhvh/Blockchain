import time
import serial

PORT = 'COM7'
BAUD = 115200

print(f'Testing serial port {PORT} @ {BAUD}')
try:
    s = serial.Serial(PORT, BAUD, timeout=2)
except Exception as e:
    print('OPEN_FAILED', e)
    raise SystemExit(1)

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
