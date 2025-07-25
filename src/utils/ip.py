from starlette.requests import Request

async def get_real_ip(request: Request):
    if "x-forwarded-for" in request.headers and request.client.host in ["127.0.0.1", "172.20.0.1"]:
        ip = request.headers["x-forwarded-for"].split(",")[0].strip()
    else:
        ip = request.client.host
    return ip