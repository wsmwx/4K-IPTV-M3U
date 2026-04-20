import requests
import os
import re
import time
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor

# ================= 配置区域 =================
# 1. Quake 接口配置
TEMPLATE_DIR = "rtp"                                  # 母版文件夹名称

# 2. GitHub 推送配置
# 提交说明前缀；为空时使用默认文案
GITHUB_COMMIT_PREFIX = "Auto update"
# ============================================
EPG_URL = "http://epg.51zmt.top:8000/e.xml.gz"
TVG_LOGO_URL = "https://gcore.jsdelivr.net/gh/taksssss/tv/icon/.png"

# 中国省份全称及简称对照表，用于智能嗅探
PROVINCES = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", 
             "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", 
             "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", 
             "甘肃", "青海", "宁夏", "新疆"]

def get_root_domain(domain):
    """提取根域名，防 DDNS 假去重"""
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', domain): return domain
    parts = domain.split('.')
    if len(parts) >= 3:
        if parts[-2] in ['com', 'net', 'org', 'gov', 'edu', 'gx'] or len(parts[-2]) <= 2:
            return ".".join(parts[-3:])
        else: return ".".join(parts[-2:])
    return domain

def extract_province(filename):
    """智能识别省份"""
    for p in PROVINCES:
        if p in filename: return p
    return None

def check_url(url):
    """16KB 深度硬核测流验证 (拒绝假存活)"""
    try:
        with requests.get(url, stream=True, timeout=(3, 5)) as resp:
            if resp.status_code == 200:
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk: downloaded += len(chunk)
                    if downloaded >= 16384:
                        print(f"  [√ 真有效] {url}")
                        return url
    except Exception: pass
    return None

def check_and_clear_existing(txt_file, m3u_file):
    """检测当前目录文件，失效则雷霆清空"""
    if not os.path.exists(txt_file): return False
    urls = []
    try:
        with open(txt_file, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.search(r'https?://[^\s,]+', line)
                if match: urls.append(match.group())
                if len(urls) >= 2: break
    except Exception: return False

    if urls:
        print(f"[*] 测试现有文件 [{txt_file}] ...")
        for url in urls:
            if check_url(url):
                print(f"[!] 结论: 源依然坚挺，跳过本省份。")
                return True
    
    print(f"[*] 结论: 源已失效，正在清空旧文件...")
    for file in [txt_file, m3u_file]:
        with open(file, 'w', encoding='utf-8') as f: f.write("") 
    return False

def get_quake_assets(province):
    """针对指定省份请求节点"""
    quake_token = (os.environ.get("QUAKE_TOKEN") or "").strip()
    if not quake_token:
        print("[-] 未检测到 QUAKE_TOKEN 环境变量，无法请求 Quake 接口。")
        return []

    url = "https://quake.360.net/api/v3/search/quake_service"
    query_str = f'app:"udpxy" AND is_domain:true AND province:"{province}"'
    headers = {"X-QuakeToken": quake_token, "Content-Type": "application/json"}
    payload = {"query": query_str, "start": 0, "size": 20, "is_domain": True}

    print(f"[*] 正在请求 [{province}] 地区的新节点...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200 and response.json().get('code') == 0:
            return response.json().get('data', [])
    except Exception: pass
    return []

def txt_to_m3u_format(txt_content, group_title):
    """智能转换 M3U 分组格式"""
    m3u_lines = []
    for line in txt_content.splitlines():
        line = line.strip()
        if not line: continue
        if '#genre#' in line:
            continue
        elif ',' in line:
            name, url = [p.strip() for p in line.split(',', 1)]
            m3u_lines.append(
                f'#EXTINF:-1 tvg-id="{name}" tvg-logo="{TVG_LOGO_URL}" group-title="{group_title}",{name}\n{url}'
            )
    return "\n".join(m3u_lines)

def process_province(template_filename, template_dir, txt_output_dir, m3u_output_dir):
    """单一省份核心流水线"""
    province = extract_province(template_filename)
    if not province: return

    template_path = os.path.join(template_dir, template_filename)
    out_txt = os.path.join(txt_output_dir, template_filename)
    out_m3u = os.path.join(m3u_output_dir, template_filename.replace('.txt', '.m3u'))
    group_title = os.path.splitext(template_filename)[0]

    # 1. 检测已有文件
    if check_and_clear_existing(out_txt, out_m3u): return

    # 2. 读取母版内容
    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()
    
    # 动态嗅探组播靶标 (自动识别 udp/rtp/igmp 及 IP端口)
    match = re.search(r'(?:https?://[^/,]+/)?(udp|rtp|igmp)(?:/|://)(\d+\.\d+\.\d+\.\d+:\d+)', template_content, re.IGNORECASE)
    if not match: return
    protocol, mcast_target = match.group(1).lower(), match.group(2)
    print(f"[*] 成功提取 [{province}] 测试靶标: /{protocol}/{mcast_target}")

    # 3. 获取 Quake 资产并绝对去重
    assets = get_quake_assets(province)
    if not assets: return

    urls_to_test, host_map, seen_root_domains = [], {}, set()
    for item in assets:
        domain = item.get('domain') or item.get('service', {}).get('http', {}).get('host') or item.get('hostname')
        port = item.get('port')
        if domain and port:
            pure_domain = domain.split(':')[0]
            root_domain = get_root_domain(pure_domain)
            if root_domain not in seen_root_domains:
                seen_root_domains.add(root_domain)
                full_host = f"{domain}:{port}"
                test_url = f"http://{full_host}/{protocol}/{mcast_target}"
                urls_to_test.append(test_url)
                host_map[test_url] = full_host
    
    # 4. 并发深度测流
    valid_hosts = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        for res_url in executor.map(check_url, urls_to_test):
            if res_url: valid_hosts.append(host_map[res_url])

    # 5. 克隆母版生成纯净文件
    if valid_hosts:
        pattern = re.compile(r'(?:https?://[^/,]+/)?(udp|rtp|igmp)(?:/|://)(\d+\.\d+\.\d+\.\d+:\d+)', re.IGNORECASE)
        with open(out_txt, 'w', encoding='utf-8') as f_txt, open(out_m3u, 'w', encoding='utf-8') as f_m3u:
            f_m3u.write(f'#EXTM3U x-tvg-url="{EPG_URL}"\n')
            for host in valid_hosts:
                new_txt_block = pattern.sub(f'http://{host}/\\1/\\2', template_content)
                f_txt.write(new_txt_block + "\n\n")
                f_m3u.write(txt_to_m3u_format(new_txt_block, group_title) + "\n\n")
        print(f"[+] 完美！[{province}] 更新完成，获取 {len(valid_hosts)} 个纯净节点。")
    else:
        print(f"[-] [{province}] 本次搜索全军覆没，明天再试。")

def push_to_github(files):
    """
    将本次生成文件提交并推送到当前 GitHub 仓库。
    依赖本机已配置好 git 远程与认证（SSH 或凭据管理器）。
    """
    existing_files = [f for f in files if os.path.exists(f)]
    if not existing_files:
        print("[-] 没有可推送文件，跳过 GitHub 同步。")
        return

    print("\n[*] 正在同步到 GitHub 当前仓库...")
    try:
        add_cmd = ["git", "add", "--"] + existing_files
        add_run = subprocess.run(add_cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if add_run.returncode != 0:
            print(f"[-] git add 失败:\n{add_run.stderr.strip()}")
            return

        check_run = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if check_run.returncode == 0:
            print("[*] 没有新增变更，无需提交。")
            return

        commit_msg = f"{GITHUB_COMMIT_PREFIX} multicast files at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        commit_run = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if commit_run.returncode != 0:
            print(f"[-] git commit 失败:\n{commit_run.stderr.strip()}")
            return
        print("[+] git commit 成功。")

        push_run = subprocess.run(
            ["git", "push"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if push_run.returncode != 0:
            print(f"[-] git push 失败:\n{push_run.stderr.strip()}")
            return
        print("[+] 已成功推送到 GitHub。")
    except Exception as e:
        print(f"[!] GitHub 同步异常: {e}")

def parse_args():
    ap = argparse.ArgumentParser(description="RTP 模板搜源并生成省份 txt/m3u。")
    ap.add_argument(
        "--push",
        action="store_true",
        help="生成完成后执行 git add/commit/push（默认关闭，便于在 GitHub Actions 由工作流统一提交）。",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    template_dir = os.path.join(script_dir, TEMPLATE_DIR)
    txt_output_dir = os.path.join(repo_root, "txt")
    m3u_output_dir = os.path.join(repo_root, "m3u")

    if not os.path.exists(template_dir):
        os.makedirs(template_dir)
        print(f"[!] 没有找到 '{template_dir}' 目录，已自动创建。请放入模板后重新运行！")
        return

    os.makedirs(txt_output_dir, exist_ok=True)
    os.makedirs(m3u_output_dir, exist_ok=True)

    template_files = [f for f in os.listdir(template_dir) if f.endswith('.txt')]
    if not template_files:
        print(f"[!] '{template_dir}' 目录中空空如也，请放入各省市的模板文件。")
        return

    # 流水线处理各省份
    for filename in template_files:
        print(f"\n" + "="*50)
        print(f" 正在处理兵工厂任务: {filename}")
        print("="*50)
        process_province(filename, template_dir, txt_output_dir, m3u_output_dir)
    
    generated_files = []
    generated_files.extend(
        [os.path.join("txt", f) for f in os.listdir(txt_output_dir) if f.endswith('.txt')]
    )
    generated_files.extend(
        [os.path.join("m3u", f) for f in os.listdir(m3u_output_dir) if f.endswith('.m3u')]
    )
    if args.push:
        print("\n[] 流水线本地文件生成完毕，准备执行 GitHub 同步...")
        push_to_github(generated_files)
        print("\n[] 史诗级闭环！全网搜源 -> 深度测流 -> 覆盖生成 -> GitHub 发布，全部完成！")
    else:
        print("\n[] 流水线本地文件生成完毕（未启用 --push，跳过 git 推送）。")
        print(f"[] 本次生成文件数量: {len(generated_files)}")

if __name__ == '__main__':
    main()