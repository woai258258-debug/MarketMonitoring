# -*- coding: utf-8 -*-
"""云端探测 v2：curl 多页时间序列 + Chrome headless 对比"""
import json, re, subprocess, sys, tempfile, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def curl(url, timeout=20):
    tmp = tempfile.mktemp(suffix=".html")
    cmd = ["curl", "-s", "-L", "--compressed", "--max-time", str(timeout), "-A", UA,
           "-H", "Referer: https://guba.eastmoney.com/", "-o", tmp, "-w", "%{http_code}", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        body = open(tmp, "r", encoding="utf-8", errors="replace").read() if os.path.exists(tmp) else ""
        return r.stdout.strip(), body
    except Exception as e:
        return "ERR", str(e)
    finally:
        try: os.remove(tmp)
        except OSError: pass

def parse_rows(html):
    rows = []
    for tr_m in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_m.group(1), re.S)
        if len(tds) < 5: continue
        clean = lambda x: re.sub(r'<[^>]+>', '', x).strip()
        rows.append(clean(tds[4]))
    return rows

print("=== curl 多页时间序列 ===")
for p in [1, 2, 5, 10, 20, 35, 50, 70]:
    code, html = curl(f"https://guba.eastmoney.com/list,zssh000001,f_{p}.html")
    rows = parse_rows(html)
    times = [t for t in rows if re.match(r'^\d{1,2}-\d{1,2} \d{2}:\d{2}$', t)]
    if times:
        print(f"  f_{p}: {len(times)} 时间 | 首 {times[0]} | 末 {times[-1]} | 前3 {times[:3]}")
    else:
        print(f"  f_{p}: 无有效时间 http={code} size={len(html)}")

print("\n=== Chrome headless 测试 ===")
chrome = None
for c in ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
          "/usr/bin/chromium-browser", "/usr/bin/chromium.chrome"]:
    if os.path.exists(c): chrome = c; break
print("Chrome 路径:", chrome)
if chrome:
    tmp = tempfile.mktemp(suffix=".html")
    try:
        r = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                            "--dump-dom", "--virtual-time-budget=8000",
                            "https://guba.eastmoney.com/list,zssh000001,f_1.html"],
                           capture_output=True, timeout=40)
        html = r.stdout.decode("utf-8", errors="replace")
        rows = parse_rows(html)
        times = [t for t in rows if re.match(r'^\d{1,2}-\d{1,2} \d{2}:\d{2}$', t)]
        print(f"  dump-dom 大小 {len(html)} | 时间 {len(times)} | 前5 {times[:5]}")
        if not times and r.stderr:
            print("  stderr:", r.stderr.decode('utf-8', errors='replace')[:300])
    except Exception as e:
        print("  Chrome 运行失败:", e)
else:
    print("  未找到 Chrome")
