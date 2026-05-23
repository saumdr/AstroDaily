#!/usr/bin/env python3
"""
AstroDaily 自动化任务
每天早上9点检查 arXiv 是否有新论文，如果有则更新日报并部署
"""
import os
import sys
import json
import time
import subprocess
from datetime import datetime
from pathlib import Path

# 配置
WORK_DIR = r"D:\MyProgramm\WorkBuddy"
PYTHON_EXE = r"C:\Users\gan\AppData\Local\Programs\Python\Python38\python.exe"
DEPLOY_DIR = os.path.join(WORK_DIR, "astro-daily-live")
ARCHIVES_DIR = os.path.join(WORK_DIR, "astro-daily-archives")
DEPLOY_DOMAIN = "astro-daily-latest.surge.sh"
LOG_FILE = os.path.join(WORK_DIR, "update.log")

def log(msg):
    """写入日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_msg + '\n')

def run_command(cmd, cwd=None):
    """运行命令并返回输出"""
    log(f"执行命令: {cmd}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or WORK_DIR,
            capture_output=True,
            text=True,
            timeout=600  # 10分钟超时
        )
        
        if result.stdout:
            log(f"输出: {result.stdout[:500]}")
        if result.stderr:
            log(f"错误: {result.stderr[:500]}")
            
        return result.returncode == 0, result.stdout, result.stderr
        
    except subprocess.TimeoutExpired:
        log("❌ 命令执行超时（10分钟）")
        return False, "", "Timeout"
    except Exception as e:
        log(f"❌ 命令执行失败: {e}")
        return False, "", str(e)

def get_latest_arxiv_papers():
    """
    检查 arXiv 是否有新论文
    返回 (has_new, latest_date)
    """
    log("🔍 检查 arXiv 最新论文...")
    
    # 运行 Python 脚本获取最新论文日期
    cmd = f'"{PYTHON_EXE}" -c "import astro_daily; print(astro_daily.get_latest_paper_date())"'
    success, stdout, stderr = run_command(cmd)
    
    if not success:
        log("⚠️  无法获取最新论文日期，将强制更新")
        return True, None
    
    latest_date = stdout.strip()
    log(f"📅 arXiv 最新论文日期: {latest_date}")
    
    # 检查本地是否已有该日期的日报
    if latest_date:
        local_file = os.path.join(ARCHIVES_DIR, f"astro-daily-{latest_date}.html")
        if os.path.exists(local_file):
            log(f"✅ 已存在 {latest_date} 的日报，无需更新")
            return False, latest_date
    
    return True, latest_date

def generate_daily_report():
    """生成日报"""
    log("📝 开始生成日报...")
    
    cmd = f'"{PYTHON_EXE}" astro_daily.py'
    success, stdout, stderr = run_command(cmd)
    
    if not success:
        log("❌ 日报生成失败")
        return False
    
    log("✅ 日报生成成功")
    return True

def deploy_to_surge():
    """部署到 Surge.sh"""
    log("🚀 开始部署到 Surge...")
    
    # 复制最新日报到部署目录
    archives = sorted(Path(ARCHIVES_DIR).glob("astro-daily-*.html"), reverse=True)
    
    if not archives:
        log("❌ 没有找到日报文件")
        return False
    
    latest_file = archives[0]
    log(f"📦 准备部署: {latest_file.name}")
    
    # 复制为 index.html
    import shutil
    dest_file = os.path.join(DEPLOY_DIR, "index.html")
    shutil.copy2(latest_file, dest_file)
    log(f"✅ 已复制到: {dest_file}")
    
    # 部署到 Surge
    cmd = f'npx surge "{DEPLOY_DIR}" {DEPLOY_DOMAIN} --force'
    success, stdout, stderr = run_command(cmd)
    
    if not success:
        log("❌ 部署失败")
        return False
    
    log("✅ 部署成功！")
    log("🌐 访问地址: " + DEPLOY_DOMAIN)
    return True

def send_notification(msg):
    """发送通知（可选：微信、邮件等）"""
    # TODO: 如果需要，可以添加通知功能
    log(f"📢 通知: {msg}")

def main():
    """主函数"""
    log("=" * 60)
    log("🌌 AstroDaily 自动任务开始")
    log("=" * 60)
    
    try:
        # 1. 检查是否有新论文
        has_new, latest_date = get_latest_arxiv_papers()
        
        if not has_new:
            log("ℹ️  没有新论文，任务结束")
            send_notification("AstroDaily: 今日无新论文")
            return
        
        # 2. 生成日报
        if not generate_daily_report():
            log("❌ 日报生成失败，任务终止")
            send_notification("AstroDaily: 日报生成失败！")
            return
        
        # 3. 部署到公网
        if not deploy_to_surge():
            log("❌ 部署失败，任务终止")
            send_notification("AstroDaily: 部署失败！")
            return
        
        # 4. 成功
        log("=" * 60)
        log("✅ AstroDaily 自动任务完成！")
        log("=" * 60)
        send_notification("AstroDaily: 日报已更新并部署成功！")
        
    except Exception as e:
        log(f"❌ 任务执行出错: {e}")
        import traceback
        log(traceback.format_exc())
        send_notification(f"AstroDaily: 任务执行出错 - {e}")

if __name__ == "__main__":
    main()
