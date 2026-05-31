import requests

u = "http://172.20.10.2:4747/videofeed"

try:
    r = requests.get(u, timeout=4)

    print("status:", r.status_code)
    print("content-type:", r.headers.get("content-type"))

except Exception as e:
    print("Lỗi:", e)