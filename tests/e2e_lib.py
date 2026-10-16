"""시험용 HTTP 클라이언트 (쿠키 유지) + multipart 만들기."""
import io, json, uuid, http.cookiejar, urllib.request, urllib.error
BASE = "http://127.0.0.1:8020"

class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def req(self, method, path, data=None, ctype=None):
        headers = {}
        if isinstance(data, (dict, list)):
            data, headers["content-type"] = json.dumps(data).encode(), "application/json"
        elif ctype:
            headers["content-type"] = ctype
        r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            with self.op.open(r, timeout=180) as res:  # 이미지 판정은 1분 가까이 걸린다
                body = res.read()
                return res.status, (json.loads(body) if res.headers.get("content-type", "").startswith("application/json") else body)
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, body


def multipart(fields, files):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fn, data) in files.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: application/pdf\r\n\r\n'.encode())
        out.write(data + b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


