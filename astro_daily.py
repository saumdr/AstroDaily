#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AstroDaily · 天体物理日报生成器
从 arXiv astro-ph 抓取论文，生成带翻译功能的日报 HTML
"""

import sys
import os
import time
import re
import json
import datetime
import urllib.request
import urllib.parse
import html as html_mod
import xml.etree.ElementTree as ET

# ── 配置 ─────────────────────────────────────────────
PAPERS_PER_DAY = 30
OUTPUT_DIR = "astro-daily-archives"
ARCHIVE_LIMIT = 30
TEMPLATE_FILE = "astro-daily-template.html"
INDEX_TEMPLATE_FILE = "astro-index-template.html"


# ── 抓取 arXiv ───────────────────────────────────────────
def fetch_arxiv_papers(max_results=PAPERS_PER_DAY, retry=3):
    """从 arXiv API 抓取 astro-ph 分类最新论文，带重试。"""
    url = (
        "http://export.arxiv.org/api/query?"
        + urllib.parse.urlencode({
            "search_query": "cat:astro-ph.*",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": str(max_results),
        })
    )
    xml_data = ""
    for attempt in range(retry):
        try:
            print("[arXiv] 抓取最新 %d 篇天体物理论文（尝试 %d/%d）..." % (max_results, attempt+1, retry))
            req = urllib.request.Request(url, headers={"User-Agent": "AstroDaily/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                xml_data = resp.read().decode("utf-8")
            break
        except Exception as e:
            print("  [重试] arXiv 请求失败：" + str(e)[:80])
            if attempt < retry - 1:
                wait = 5 * (attempt + 1)
                print("  %d 秒后重试..." % wait)
                time.sleep(wait)
            else:
                print("[错误] arXiv 抓取失败，放弃。")
                return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", ns)
    papers = []
    total = len(entries)
    for i, entry in enumerate(entries):
        title     = entry.find("atom:title", ns)
        summary   = entry.find("atom:summary", ns)
        published = entry.find("atom:published", ns)
        link      = entry.find("atom:id", ns)
        title_t  = title.text.strip().replace("\n", " ").replace("  ", " ") if title is not None else ""
        summary_t = summary.text.strip().replace("\n", " ") if summary is not None else ""
        pub_t     = published.text[:10] if published is not None else ""
        url_t      = link.text if link is not None else ""
        authors = entry.findall("atom:author", ns)
        author_names = []
        for a in authors:
            name_el = a.find("atom:name", ns)
            if name_el is not None:
                author_names.append(name_el.text.strip())
        papers.append({
            "title_en": title_t,
            "summary_en": summary_t,
            "published": pub_t,
            "url": url_t,
            "authors": author_names,
        })
        print("  [%d/%d] %s" % (i+1, total, title_t[:50]))
    print("[完成] 共 %d 篇" % len(papers))
    return papers


# ── AI 摘要 & 概念提取（调用本地 LLM）────────────
def summarize_brief(prompt, temperature=0.3):
    """调用本地 LLM 生成摘要。"""
    try:
        import subprocess, tempfile
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        with open(path, "r", encoding="utf-8") as f:
            result = subprocess.run(
                ["ollama", "run", "phi3:mini", "--temperature", str(temperature)],
                stdin=f,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", timeout=120,
            )
        os.unlink(path)
        out = result.stdout.strip()
        if out.startswith("<think>"):
            out = out[out.find("</think>") + 4:].strip()
        return out[:500]
    except Exception as e:
        print("  [LLM 错误] " + str(e)[:60])
        return ""


def extract_concepts(text, temperature=0.2):
    """从文本中提取天体物理概念。"""
    prompt = (
        "请从以下天体物理学英文摘要中提取 3-5 个核心专业概念或术语，"
        "每行一个，格式：概念名::一句话中文解释（不超过 25 字）。\n\n" + text[:1500]
    )
    try:
        import subprocess, tempfile
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        with open(path, "r", encoding="utf-8") as f:
            result = subprocess.run(
                ["ollama", "run", "phi3:mini", "--temperature", str(temperature)],
                stdin=f,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", timeout=90,
            )
        os.unlink(path)
        out = result.stdout.strip()
        if out.startswith("<think>"):
            out = out[out.find("</think>") + 4:].strip()
        concepts = []
        for line in out.splitlines():
            line = line.strip()
            if "::" in line:
                parts = line.split("::", 1)
                concepts.append((parts[0].strip(), parts[1].strip()[:40]))
        return concepts[:5]
    except Exception as e:
        print("  [概念提取错误] " + str(e)[:60])
        return []


def make_key_points(summary_en, temperature=0.3):
    """生成 3 个关键发现要点。"""
    prompt = (
        "请从以下天体物理论文摘要中提取 3 个最重要的关键发现或核心结论。"
        "只输出要点列表，每行一个，格式如下：\n"
        "1. [要点1]\n"
        "2. [要点2]\n"
        "3. [要点3]\n\n"
        "注意：不要输出摘要原文，不要输出任何解释性文字，只输出 3 个要点。每个要点不超过 80 字。\n\n"
        + summary_en[:2000]
    )
    try:
        import subprocess, tempfile
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        with open(path, "r", encoding="utf-8") as f:
            result = subprocess.run(
                ["ollama", "run", "phi3:mini", "--temperature", str(temperature)],
                stdin=f,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", timeout=90,
            )
        os.unlink(path)
        out = result.stdout.strip()
        if out.startswith("<think>"):
            out = out[out.find("</think>") + 4:].strip()
        points = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            line = line.lstrip("1234567890.-• ")
            if line and len(line) > 10 and len(line) < 300:
                points.append(line[:200])
        # 如果 LLM 返回了整段摘要（通常只有 1 个点且很长），回退到摘要分句
        if len(points) == 1 and len(points[0]) > 300:
            sentences = summary_en.split('. ')
            points = [s.strip() + '.' for s in sentences[:3] if len(s.strip()) > 20]
        if not points:
            sentences = summary_en.split('. ')
            points = [s.strip() + '.' for s in sentences[:3] if len(s.strip()) > 20]
        return points[:5]
    except Exception as e:
        print("  [要点生成错误] " + str(e)[:60])
        return []


# ── 分类 ─────────────────────────────────────────────
def categorize(papers):
    """将论文按版块分类。"""
    groups = {
        "星系与宇宙学": [],
        "恒星与系外行星": [],
        "高能天体物理": [],
        "仪器与方法": [],
        "其他": [],
    }
    for p in papers:
        title = p["title_en"].lower()
        summary = p["summary_en"].lower()
        full = title + " " + summary
        if any(w in full for w in ["galaxy", "cosmology", "dark matter", "dark energy", "cmb", "large-scale", "reionization"]):
            groups["星系与宇宙学"].append(p)
        elif any(w in full for w in ["star", "stellar", "planet", "exoplanet", "asteroseismology", "supernova", "white dwarf", "neutron star"]):
            groups["恒星与系外行星"].append(p)
        elif any(w in full for w in ["grb", "gamma-ray", "x-ray", "gravitational wave", "black hole", "agn", "quasar", "jet", "flare"]):
            groups["高能天体物理"].append(p)
        elif any(w in full for w in ["instrument", "telescope", "mission", "survey", "method", "technique", "algorithm", "machine learning", "pipeline"]):
            groups["仪器与方法"].append(p)
        else:
            groups["其他"].append(p)
    return groups


# ── 生成卡片 HTML ─────────────────────────────────────

def translate_to_zh(text):
    """用 MyMemory API 把英文翻译成中文（Python 端）。"""
    if not text or len(text.strip()) < 5:
        return text
    try:
        import json, urllib.request, urllib.parse
        url = ("https://api.mymemory.translated.net/get?q="
                + urllib.parse.quote(text[:400])
                + "&langpair=en|zh-CN")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("responseStatus") == 200:
            return data["responseData"]["translatedText"]
    except Exception:
        pass
    return text



_LAYMAN_TERMS = [
    ("暗物质",       "暗物质（一种看不见、摸不着，但科学家认为存在的神秘物质）"),
    ("暗能量",       "暗能量（一种让宇宙加速膨胀的神秘力量）"),
    ("黑洞",         "黑洞（引力超级强，连光都逃不出来的天体）"),
    ("引力波",       "引力波（时空本身的涟漪，像石头扔进水里产生的波纹）"),
    ("超新星",       "超新星（恒星爆炸，瞬间亮度可以超过整个星系）"),
    ("中子星",       "中子星（恒星坍缩后密度极高的小星星，一勺重几十亿吨）"),
    ("白矮星",       "白矮星（像太阳这样的恒星老去后剩下的致密核心）"),
    ("系外行星",     "系外行星（太阳系以外、绕着其他恒星转的行星）"),
    ("红移",         "红移（光波长被拉长，说明天体在远离我们）"),
    ("星际介质",     "星际介质（恒星之间的气体和尘埃，是新恒星的原材料）"),
    ("银河系",       "银河系（我们所在的这个棒旋星系，太阳是其中一颗普通恒星）"),
    ("宇宙微波背景", "宇宙微波背景（大爆炸留下的余热，像宇宙的婴儿照片）"),
    ("弱透镜",       "弱透镜（远处星系的光被中间的物质扭曲，用来称宇宙的体重）"),
    ("光谱",         "光谱（把光拆成彩虹，每个元素都有独特的指纹）"),
    ("吸积盘",       "吸积盘（物质绕着黑洞或恒星旋转，像水流进下水道前形成的盘）"),
    ("喷流",         "喷流（从黑洞或年轻恒星两极喷出的高速物质流）"),
    ("星团",         "星团（一大群恒星出生在同一片云里，像宇宙的幼儿园）"),
    ("光变曲线",     "光变曲线（天体亮度随时间变化的曲线，像恒星的心电图）"),
    ("径向速度",     "径向速度（天体沿着视线方向的运动速度，通过光谱摇摆测得）"),
    ("凌星",         "凌星（行星从恒星前面经过，让恒星稍微变暗）"),
    ("原行星盘",     "原行星盘（新生恒星周围的气体尘埃盘，行星在这里出生）"),
    ("光球层",       "光球层（太阳表面我们能看到的最底层，所有的光从这里发出）"),
    ("日冕",         "日冕（太阳最外层的稀薄大气，温度高达几百万度）"),
    ("太阳黑子",     "太阳黑子（太阳表面温度较低的区域，看起来比较暗）"),
    ("太阳耀斑",     "太阳耀斑（太阳表面突然爆发能量，像打了一个巨大的喷嚏）"),
    ("MHD",          "MHD（磁流体力学，研究磁场和带电气体如何一起跳舞）"),
    ("湍流",         "湍流（流体混乱不规则的运动，像湍急的河流）"),
    ("数值模拟",     "数值模拟（用计算机假装宇宙，看看理论对不对）"),
    ("哈勃常数",     "哈勃常数（描述宇宙膨胀速度的数值）"),
    ("大尺度结构",   "大尺度结构（星系在宇宙中分布形成的网状结构）"),
    ("丝状结构",     "丝状结构（星系聚集形成的宇宙高速公路，连接着各个星系团）"),
    ("事件视界",     "事件视界（黑洞的不归路边界，进去就出不来）"),
    ("吸积",         "吸积（物质被引力吸引，螺旋式落向中心天体的过程）"),
    ("X射线",        "X射线（能量很高的光，一般来自极高温或高速运动的地方）"),
    ("伽马射线暴",   "伽马射线暴（宇宙中突然出现的超强伽马射线闪光）"),
    ("脉冲星",       "脉冲星（高速旋转的中子星，像宇宙中的灯塔）"),
    ("超新星遗迹",   "超新星遗迹（恒星爆炸后留下的膨胀气体壳）"),
    ("行星状星云",   "行星状星云（太阳这样的恒星老去时抛出的气体壳）"),
    ("宇宙射线",     "宇宙射线（从外太空飞来的高能粒子，像宇宙的子弹）"),
    ("太阳风",       "太阳风（太阳向外吹出的带电粒子流）"),
    ("核聚变",       "核聚变（轻原子核结合成更重的核，同时释放巨大能量的过程）"),
    ("詹姆斯·韦布",  "詹姆斯·韦布（JWST，红外线超级强的太空望远镜）"),
    ("韦布",         "韦布（JWST 望远镜的简称）"),
]



def _add_layman_terms(text):
    """在中文文本中，为专业术语自动添加括号通俗解释。"""
    result = text
    for term, explanation in _LAYMAN_TERMS:
        # 避免重复添加
        if term in result and explanation.split("（")[0] + "（" not in result:
            result = result.replace(term, explanation, 1)
    return result




def make_layman_explanation(summary_en):
    """
    生成通俗解释（使用智能规则引擎）。
    返回结构化的英文解释文本，由前端 JS 翻译成中文。
    输出格式：一段话说明"这篇论文做了什么 + 为什么重要"。
    """
    # ── 智能规则引擎生成解释 ──────────────────────────
    s = summary_en.lower()
    
    # 提取摘要中的关键动词和名词短语
    sentences = summary_en.split('. ')
    first_sentence = sentences[0] if sentences else summary_en
    
    # 识别具体研究对象（更精确）
    topics = []
    topic_desc = ""
    if "black hole" in s:
        topics.append("黑洞")
        topic_desc = "一种引力极强、连光都无法逃脱的天体"
    elif "supernova" in s or "nova" in s:
        topics.append("超新星爆发")
        topic_desc = "恒星死亡时的剧烈爆炸，亮度可超过整个星系"
    elif "neutron star" in s or "pulsar" in s:
        topics.append("中子星")
        topic_desc = "恒星坍缩后的致密天体，密度大到一勺物质重几十亿吨"
    elif "white dwarf" in s:
        topics.append("白矮星")
        topic_desc = "像太阳这样的恒星燃尽后留下的致密残骸"
    elif "exoplanet" in s or ("planet" in s and "solar" not in s):
        topics.append("系外行星")
        topic_desc = "围绕其他恒星运转的行星，可能孕育生命"
    elif "galaxy" in s or "milky way" in s:
        topics.append("星系")
        topic_desc = "由数千亿颗恒星组成的巨大天体系统"
    elif "dark matter" in s:
        topics.append("暗物质")
        topic_desc = "宇宙中看不见但占据大部分质量的神秘物质"
    elif "dark energy" in s:
        topics.append("暗能量")
        topic_desc = "推动宇宙加速膨胀的未知力量"
    elif "gravitational wave" in s:
        topics.append("引力波")
        topic_desc = "时空的涟漪，像石头扔进水面产生的波纹"
    elif "cosmic ray" in s:
        topics.append("宇宙射线")
        topic_desc = "来自宇宙深处的高能粒子"
    elif "solar" in s or "sun" in s:
        topics.append("太阳")
        topic_desc = "我们太阳系的中心恒星"
    elif "star" in s:
        topics.append("恒星")
        topic_desc = "像太阳一样自身发光的天体"
    elif "turbulence" in s:
        topics.append("湍流")
        topic_desc = "气体或流体中混乱无序的运动"
    elif "magnetic field" in s:
        topics.append("磁场")
        topic_desc = "影响带电粒子运动的隐形力场"
    else:
        topics.append("天体物理现象")
        topic_desc = "宇宙中的物理过程"
    
    # 识别研究方法
    method = ""
    method_desc = ""
    if "simulation" in s or "numerical" in s:
        method = "数值模拟"
        method_desc = "用超级计算机模拟宇宙演化，就像用飞行模拟器训练飞行员"
    elif "observation" in s or "observed" in s or "survey" in s or "data" in s:
        method = "观测"
        method_desc = "用望远镜收集来自宇宙的光信号"
    elif "theory" in s or "analytical" in s or "analytic" in s:
        method = "理论分析"
        method_desc = "用数学方程推导和预测天体行为"
    elif "machine learning" in s or "neural network" in s or "deep learning" in s:
        method = "机器学习"
        method_desc = "让AI从海量数据中自动寻找规律"
    
    # 识别核心发现/结论
    finding = ""
    if "first" in s or "first time" in s:
        finding = "首次获得了相关观测证据"
    elif "confirm" in s or "confirmed" in s or "verification" in s:
        finding = "验证了此前科学家的理论预测"
    elif "constrain" in s or "constraint" in s or "limit" in s:
        finding = "对现有理论模型提出了更精确的限制"
    elif "discover" in s or "discovery" in s or "found" in s:
        finding = "发现了新的现象或规律"
    elif "evidence" in s:
        finding = "找到了支持某种理论的新证据"
    else:
        finding = "深入探索了其物理机制"
    
    # 识别科学意义
    significance = ""
    if "habitable" in s or "life" in s or "biosignature" in s:
        significance = "这有助于我们判断宇宙中是否存在其他宜居星球，回答人类是否孤独这一终极问题"
    elif "dark matter" in s or "dark energy" in s:
        significance = "这是理解宇宙组成和命运的关键，暗物质和暗能量占据了宇宙总能量的95%以上"
    elif "black hole" in s:
        significance = "黑洞是宇宙中最极端的天体，研究它能帮助我们理解引力的本质"
    elif "gravitational wave" in s:
        significance = "引力波为人类打开了一扇全新的观测宇宙的窗口，让我们能'听'到宇宙的动静"
    elif "early universe" in s or "primordial" in s or "cosmic dawn" in s:
        significance = "这让我们得以窥见宇宙婴儿时期的样子，理解万物起源"
    elif "exoplanet" in s or "planet" in s:
        significance = "寻找系外行星是人类探索太空家园的重要一步"
    elif "star formation" in s:
        significance = "恒星是宇宙的炼金术士，研究它们的诞生有助于理解元素的起源"
    elif "galaxy" in s:
        significance = "星系是宇宙的基本建筑单元，理解它们的演化就是理解宇宙的演化"
    else:
        significance = "这一研究加深了我们对宇宙运行机制的理解"
    
    # 组装解释
    topic_str = topics[0] if topics else "天体物理现象"
    
    explanation = f"这篇论文研究{topic_str}"
    if topic_desc:
        explanation += f"——{topic_desc}"
    explanation += "。"
    
    if method:
        explanation += f"科学家通过{method}的方法，{method_desc}，{finding}。"
    else:
        explanation += f"研究发现：{finding}。"
    
    explanation += significance
    
    # 添加类比
    analogy = ""
    if "simulation" in s:
        analogy = "就像气象学家用计算机模拟台风路径来预测天气一样"
    elif "observation" in s or "telescope" in s:
        analogy = "就像考古学家通过挖掘化石来还原远古生物的样子"
    elif "black hole" in s:
        analogy = "就像通过观察漩涡的水流来理解深海黑洞"
    elif "gravitational wave" in s:
        analogy = "就像通过水面涟漪来推断水下发生了什么"
    elif "exoplanet" in s:
        analogy = "就像通过观察远处灯光的闪烁来判断房间里有没有人"
    elif "dark matter" in s:
        analogy = "就像通过观察烟雾的飘动来推断看不见的风的方向"
    else:
        analogy = "就像通过脚印来推断走过的是什么动物"
    
    if analogy:
        explanation += f"{analogy}，天文学家也是通过各种蛛丝马迹来探索宇宙的奥秘。"
    
    if len(explanation) > 500:
        explanation = explanation[:497] + "…"
    
    return explanation

def _simplify_english(text):
    """把英文专业术语替换成 '术语（大白话）' 格式。"""
    replacements = [
        # 天体/现象
        ("supernova(e|s)?",        "supernova (a huge star explosion)"),
        ("neutron star(s)?",     "neutron star (a tiny, super-dense dead star)"),
        ("white dwarf(s)?",     "white dwarf (the small, dense leftover of a sun-like star)"),
        ("black hole(s)?",       "black hole (an object so heavy that not even light can escape)"),
        ("dark matter",          "dark matter (mysterious invisible stuff that makes up most of the universe)"),
        ("dark energy",          "dark energy (a mysterious force that makes the universe expand faster)"),
        ("gravitational wave(s)?", "gravitational wave (a ripple in space itself, like a stone thrown in water)"),
        ("gamma-ray burst(s)?",  "gamma-ray burst (a super-bright flash of high-energy light from space)"),
        ("pulsar(s)?",          "pulsar (a spinning neutron star that beams like a lighthouse)"),
        ("magnetar(s)?",        "magnetar (a neutron star with an insanely strong magnetic field)"),
        ("exoplanet(s)?",        "exoplanet (a planet orbiting a star other than our Sun)"),
        # 观测/仪器
        ("spectroscopy",          "spectroscopy (splitting light into colors to read the 'fingerprint' of elements)"),
        ("spectrum|spectra",    "spectrum (the rainbow of colors from light, which reveals what something is made of)"),
        ("redshift",              "redshift (when light stretches to red, meaning the object is moving away)"),
        ("blueshift",             "blueshift (when light compresses to blue, meaning the object is approaching)"),
        ("interstellar medium",    "interstellar medium (the thin gas and dust between stars)"),
        ("cosmic ray(s)?",       "cosmic ray (high-energy particles flying through space like tiny bullets)"),
        ("accretion disk",        "accretion disk (a spinning disk of stuff falling toward a black hole or star)"),
        ("jet(s)?|outflow(s)?",  "jet (a high-speed stream of particles shot out from near a black hole or young star)"),
        # 方法/概念
        ("magnetohydrodynamics|MHD", "magnetohydrodynamics (the study of how magnetic fields and electrified gas dance together)"),
        ("turbulence",            "turbulence (chaotic, swirling motion in a fluid, like a bumpy airplane ride)"),
        ("numerical simulation",   "numerical simulation (using a computer to 'pretend' the universe and see if the theory works)"),
        ("Bayesian inference",     "Bayesian inference (a math method that updates guesses as new evidence arrives)"),
        ("signal-to-noise",       "signal-to-noise (the ratio of useful info to useless background noise)"),
        ("angular resolution",      "angular resolution (how sharply a telescope can see two close-together points)"),
        ("adaptive optics",       "adaptive optics (a trick that removes atmospheric blur, like giving a telescope anti-shake goggles)"),
        ("interferometer",        "interferometer (linking multiple telescopes to act like one giant telescope)"),
        # 宇宙学
        ("cosmic microwave background|CMB", "cosmic microwave background (faint glow left over from the Big Bang, like the universe's baby photo)"),
        ("baryon acoustic oscillation", "baryon acoustic oscillation (sound waves from the early universe, used to measure cosmic history)"),
        ("weak lensing",          "weak lensing (when invisible matter bends light from distant galaxies, letting us 'weigh' the universe)"),
        ("Hubble constant",       "Hubble constant (the number that tells us how fast the universe is expanding)"),
        ("inflation",             "inflation (a super-fast expansion right after the Big Bang, like the universe had a growth spurt)"),
        ("large-scale structure",   "large-scale structure (the cosmic web of galaxies and empty voids, like the universe's nervous system)"),
        ("filament(s)?",         "filament (the 'highways' of galaxies, where most galaxies live in the cosmic web)"),
        ("void(s)?",             "void (a relatively empty region in the universe, like a cosmic canyon)"),
        ("dark matter halo",      "dark matter halo (an invisible cloud of dark matter surrounding a galaxy)"),
        # 恒星
        ("proto-stellar|protostar", "protostar (a baby star still gathering gas and dust)"),
        ("main sequence",         "main sequence (the 'adult' phase of a star, steadily burning hydrogen like our Sun)"),
        ("helium flash",          "helium flash (a sudden ignition of helium in an old star's core)"),
        ("stellar oscillation|asteroseismology", "stellar oscillation (studying how a star 'rings' to learn its inner structure, like a CT scan for stars)"),
        ("stellar wind",          "stellar wind (streams of particles blowing off a star, like the Sun's solar wind)"),
        # 星系
        ("galaxy evolution",      "galaxy evolution (the 'life story' of how a galaxy changes from birth to now)"),
        ("galaxy formation",      "galaxy formation (how the first clumps of gas collapsed to become galaxies)"),
        ("active galactic nucleus|AGN", "active galactic nucleus (the super-bright center of a galaxy where a black hole is 'eating' and glowing fiercely)"),
        ("quasar(s)?",          "quasar (the ultra-bright center of a distant galaxy with a Feeding black hole)"),
        ("starburst",             "starburst (when a galaxy goes crazy making new stars all at once)"),
        ("green valley",          "green valley (the transition phase when a galaxy stops making new stars and turns from blue to red)"),
        # 系外行星
        ("transit method|transit", "transit method (when a planet passes in front of its star and dims the light slightly, like a tiny eclipse)"),
        ("radial velocity method", "radial velocity method (detecting a planet by the star's tiny 'wobble' as the planet tugs on it)"),
        ("habitable zone",       "habitable zone (the 'Goldilocks' distance from a star where liquid water could exist)"),
        # 太阳
        ("solar flare",          "solar flare (a sudden burst of energy from the Sun's surface, like a giant sneeze)"),
        ("coronal mass ejection|CME", "coronal mass ejection (when the Sun throws a huge cloud of charged particles into space)"),
        ("solar wind",           "solar wind (the stream of charged particles constantly blowing off the Sun)"),
        ("photosphere",          "photosphere (the visible 'surface' of the Sun where all the light we see comes from)"),
        ("corona",               "corona (the Sun's ultra-hot outer atmosphere, visible during eclipses)"),
        ("sunspot",              "sunspot (a cooler, darker patch on the Sun's surface where magnetic fields get tangled)"),
    ]

    result = " " + text + " "
    for pattern, replacement in replacements:
        try:
            result = re.sub(r"(?i)\b" + pattern + r"\b", " " + replacement + " ", result)
        except Exception:
            pass
    return result.strip()


def _card_html(num, p, concepts, concept_modal_data, authors_str, brief, key_points_data, pub_date, layman):
    """生成单张卡片 HTML。"""
    data_en_title   = ' data-en-title="%s"'   % html_mod.escape(p["title_en"])
    data_en_summary = ' data-en-summary="%s"' % html_mod.escape(p["summary_en"])
    data_title      = ' data-title="%s"'      % html_mod.escape(p["title_en"])
    data_summary    = ' data-summary="%s"'    % html_mod.escape(p["summary_en"])
    data_meta       = ' data-meta="%s · %s"'  % (html_mod.escape(authors_str), html_mod.escape(pub_date))
    data_keypoints  = ' data-keypoints="%s"' % html_mod.escape(key_points_data)
    data_concepts   = ' data-concepts="%s"'  % html_mod.escape(concept_modal_data)
    data_url        = ' data-url="%s"'       % html_mod.escape(p["url"])
    data_layman     = ' data-layman="%s"'    % html_mod.escape(layman)

    card  = '<div class="card" style="animation-delay:%0.2fs" onclick="openModal(this)"%s%s%s%s%s%s%s%s%s>\n' % (
        (num - 1) * 0.04,
        data_en_title, data_en_summary,
        data_title, data_summary, data_meta, data_keypoints, data_concepts, data_url, data_layman
    )
    card += '  <div class="card-body">\n'
    card += '    <div class="card-header">\n'
    card += '      <div class="card-num">%d</div>\n' % num
    card += '      <div class="card-title translatable" data-en="%s">%s</div>\n' % (
        html_mod.escape(p["title_en"]), html_mod.escape(p["title_en"]))
    card += '    </div>\n'
    card += '    <div class="card-meta">%s · %s</div>\n' % (html_mod.escape(authors_str), html_mod.escape(pub_date))
    card += '    <div class="card-brief translatable" data-en="%s">%s</div>\n' % (
        html_mod.escape(brief), html_mod.escape(brief))
    if concepts:
        card += '    <div class="card-front-chips">\n'
        for cname, ctip in concepts[:3]:
            card += '      <span class="c-chip">%s</span>\n' % html_mod.escape(cname)
        card += '    </div>\n'
    card += '    <div class="card-hint">点击查看完整内容</div>\n'
    card += '  </div>\n'
    card += '</div>\n'
    return card


def generate_daily_html(papers, date_str):
    """根据论文列表和日期生成完整的日报 HTML。"""
    grouped  = categorize(papers)
    order    = ["星系与宇宙学", "恒星与系外行星", "高能天体物理", "仪器与方法", "其他"]
    sections = ""
    hero_stats = ""

    for sec in order:
        if sec not in grouped:
            continue
        items = grouped[sec]
        if not items:
            continue
        sec_id = "sec-" + sec
        color = "#a5b4fc"
        if "恒星" in sec: color = "#34d399"
        if "高能" in sec: color = "#f87171"
        if "仪器" in sec: color = "#fbbf24"
        if "其他" in sec: color = "#c084fc"
        hero_stats += (
            '  <div class="hero-stat"><div class="hero-stat-num" style="color:%s">%d</div>'
            '<div class="hero-stat-label">%s</div></div>\n' % (color, len(items), sec)
        )
        cards_html = ""
        for idx, p in enumerate(items):
            num = idx + 1
            authors_str = "、".join(p["authors"][:3])
            if len(p["authors"]) > 3:
                authors_str += " 等"
            print("  [%d/%d] 处理：%s" % (num, len(items), p["title_en"][:40]))

            # 摘要
            brief_prompt = (
                "请用 1-2 句中英文概括以下天体物理论文摘要，不超过 80 字：\n"
                + p["summary_en"][:2000]
            )
            brief = summarize_brief(brief_prompt)
            if not brief:
                sentences = p["summary_en"].split('. ')
                brief = '. '.join(s.strip() for s in sentences[:2] if s.strip())
                if not brief:
                    brief = p["summary_en"][:200]

            # 关键发现
            kps = make_key_points(p["summary_en"])
            key_points_data = "|".join(kps)

            # 概念批注
            concepts = extract_concepts(p["summary_en"][:1500])
            concept_parts = []
            for cname, ctip in concepts:
                concept_parts.append(cname + "::" + ctip)
            concept_modal_data = "|".join(concept_parts)

            # 通俗解释
            layman = make_layman_explanation(p["summary_en"])

            pub_date = (p["published"][:10] if p["published"] else date_str)
            cards_html += _card_html(
                num, p, concepts, concept_modal_data,
                authors_str, brief, key_points_data, pub_date, layman
            )

        sections += (
            '<div class="sec-anchor" id="%s"></div>\n' % sec_id
            + '<div class="section-head">\n'
            + '  <div class="section-icon">🌌</div>\n'
            + '  <h2>%s</h2>\n' % sec
            + '  <span class="count">%d</span>\n' % len(items)
            + '</div>\n'
            + '<div class="card-grid">\n'
            + cards_html
            + '</div>\n'
        )

    # 读取模板
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    # 导航链接
    nav_links = ""
    for sec in order:
        if sec in grouped and grouped[sec]:
            nav_links += '  <a class="nav-link" href="#%s">%s (%d)</a>\n' % (
                "sec-" + sec, sec, len(grouped[sec]))

    total = sum(len(grouped[s]) for s in order if s in grouped)
    template = template.replace("{{DATE_STR}}",     html_mod.escape(date_str))
    template = template.replace("{{TOTAL}}",        str(total))
    template = template.replace("{{HERO_STATS}}",  hero_stats)
    template = template.replace("{{NAV_LINKS}}",  nav_links)
    template = template.replace("{{SECTIONS_CARDS}}", sections)
    return template


# ── 存档清理 & 索引 ─────────────────────────────────
def cleanup_old():
    """删除超过 ARCHIVE_LIMIT 的旧日报。"""
    if not os.path.isdir(OUTPUT_DIR):
        return
    files = sorted([
        f for f in os.listdir(OUTPUT_DIR)
        if f.startswith("astro-daily-") and f.endswith(".html")
    ])
    while len(files) > ARCHIVE_LIMIT:
        old = files.pop(0)
        path = os.path.join(OUTPUT_DIR, old)
        print("[清理] 删除旧文件：" + old)
        os.remove(path)


def generate_index():
    """更新首页 index.html。"""
    if not os.path.isdir(OUTPUT_DIR):
        return
    files = sorted([
        f for f in os.listdir(OUTPUT_DIR)
        if f.startswith("astro-daily-") and f.endswith(".html")
    ], reverse=True)
    if not files:
        return
    cards = ""
    for f in files:
        date_part = f.replace("astro-daily-", "").replace(".html", "")
        try:
            y, m, d = date_part.split("-")
            date_label = "📅 %s 年 %s 月 %s 日" % (y, m, d)
        except Exception:
            date_label = f
        cards += (
            '  <a class="idx-card" href="%s">\n'
            '    <div class="idx-date">%s</div>\n'
            '    <div class="idx-file">%s</div>\n'
            '  </a>\n'
        ) % (f, date_label, f)
    count = len(files)
    with open(INDEX_TEMPLATE_FILE, "r", encoding="utf-8") as tpl:
        content = tpl.read()
    content = content.replace("{{ARCHIVE_COUNT}}", str(count))
    content = content.replace("{{IDX_CARDS}}", cards)
    content = content.replace("{{MAX_N}}", str(ARCHIVE_LIMIT))
    with open("index.html", "w", encoding="utf-8") as out:
        out.write(content)
    print("[索引] 已更新：index.html")


# ── 主流程 ─────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    import sys
    if len(sys.argv) > 1:
        rep_date = sys.argv[1].strip()
        print("[日期] 使用指定日期：%s" % rep_date)
    else:
        rep_date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        print("[日期] 日报日期（自动）：%s" % rep_date)

    papers = fetch_arxiv_papers(max_results=PAPERS_PER_DAY)
    if not papers:
        print("[错误] 未抓取到论文，退出。")
        return

    # 保留目标日期及前后 1 天的论文（arXiv 论文发布日期通常提前一天）
    rep_dt = datetime.date.fromisoformat(rep_date)
    allowed_dates = {
        (rep_dt - datetime.timedelta(days=1)).isoformat(),
        rep_dt.isoformat(),
        (rep_dt + datetime.timedelta(days=1)).isoformat(),
    }
    target_papers = [p for p in papers if p.get("published", "")[:10] in allowed_dates]
    if not target_papers:
        print("[跳过] %s 及其前后一天均无新论文，跳过生成。" % rep_date)
        cleanup_old()
        generate_index()
        print("\n✅ 无新内容，索引已更新。")
        return
    papers = target_papers
    print("[论文] 目标日期附近共 %d 篇论文" % len(papers))

    out_path = os.path.join(OUTPUT_DIR, "astro-daily-%s.html" % rep_date)
    print("[生成] %s 日报..." % rep_date)

    html_out = generate_daily_html(papers, rep_date)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    print("[生成] 已保存：%s" % out_path)

    cleanup_old()
    generate_index()
    print("\n✅ 全部完成！")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print("[FATAL] 未捕获的异常：")
        traceback.print_exc()
        raise
