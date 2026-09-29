from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# AI configuration
needle = 'THEMUSE_ENABLED = os.getenv("THEMUSE_ENABLED", "false").lower() == "true"'
if 'AI_PROVIDER = os.getenv("AI_PROVIDER"' not in s:
    s = s.replace(needle, needle + '\nAI_PROVIDER = os.getenv("AI_PROVIDER", "none").strip().lower()\nGEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()\nGEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()')

# Replace skill scoring with phrase-aware matching and query relevance.
old = '''    jt = tokens(text)
    for skill in CANDIDATE["skills"]:
        if skill.lower() in jt or skill.lower().replace(" ", "-") in jt:
            matched.append(skill)

    score += min(12, len(matched))
    reasons.append(f"{len(matched)} relevant skills detected")
    return min(100, score), reasons, matched
'''
new = '''    normalized_text = re.sub(r"[^a-z0-9+#.\-/ ]+", " ", text)
    normalized_text = re.sub(r"\s+", " ", normalized_text).lower()
    for skill in CANDIDATE["skills"]:
        sk = skill.lower()
        variants = {sk, sk.replace(" ", "-"), sk.replace(" ", "/")}
        if any(v in normalized_text for v in variants):
            matched.append(skill)

    skill_points = min(12, len(matched) * 2)
    score += skill_points
    if matched:
        reasons.append("Matched skills: " + ", ".join(matched[:6]))
    else:
        reasons.append("No configured skills detected")
    return min(100, score), reasons, matched
'''
if old in s:
    s = s.replace(old, new, 1)

# Add AI enrichment to each imported job, but keep it non-blocking.
old = '''        base = {**j, "salary_min": smin, "salary_max": smax, "experience_min": exp}
        sc, reasons, matched = score_job(base)
'''
new = '''        base = {**j, "salary_min": smin, "salary_max": smax, "experience_min": exp}
        try:
            if AI_PROVIDER != "none":
                from ai_engine import extract_job_intelligence
                intel = extract_job_intelligence(base["title"], base["description"])
                if isinstance(intel, dict):
                    if base.get("experience_min") is None and intel.get("experience_years") is not None:
                        base["experience_min"] = float(intel["experience_years"])
                    if base.get("salary_min") is None and intel.get("salary_min_lpa") is not None:
                        base["salary_min"] = float(intel["salary_min_lpa"])
                    if base.get("salary_max") is None and intel.get("salary_max_lpa") is not None:
                        base["salary_max"] = float(intel["salary_max_lpa"])
                    ai_skills = intel.get("required_skills") or []
                    base["_ai_skills"] = ai_skills
        except Exception:
            pass
        sc, reasons, matched = score_job(base)
        ai_skills = base.get("_ai_skills") or []
        if ai_skills:
            matched = list(dict.fromkeys(matched + [str(x) for x in ai_skills if str(x).strip()]))
            reasons.append("AI extracted required skills")
'''
if old in s:
    s = s.replace(old, new, 1)

# Make /api/discover and /api/discover/search share identical behavior with diagnostics.
if '@app.post("/api/discover/search")' not in s:
    marker='@app.post("/api/discover")'
    alias='''@app.post("/api/discover/search")
def discover_search_compat():
    try:
        return jsonify(run_discovery(request.get_json(silent=True) or {}))
    except Exception as exc:
        return jsonify({"error": "Discovery failed", "details": str(exc)[:1500]}), 502


'''
    s=s.replace(marker, alias+marker, 1)

# Provider failures should never prevent useful results.
old = '''    items, errors, source_status = search_public_sources(query, location, remote)
    try:
        results = import_job_items(items)
'''
new = '''    items, errors, source_status = search_public_sources(query, location, remote)
    try:
        results = import_job_items(items)
'''
# already hardened; leave intact

# Add provider counts to response.
old = '''        "sources_checked": source_status,
        "items_seen": len(items),
'''
new = '''        "sources_checked": source_status,
        "provider_summary": {str(x.get("source")): int(x.get("found") or 0) for x in source_status},
        "items_seen": len(items),
'''
if old in s:
    s=s.replace(old,new,1)

# Add AI status to config.
old = '''        "auto_apply_max": AUTO_APPLY_MAX,
'''
new = '''        "auto_apply_max": AUTO_APPLY_MAX,
        "ai": {
            "provider": AI_PROVIDER,
            "configured": bool((AI_PROVIDER == "gemini" and GEMINI_API_KEY) or AI_PROVIDER == "ollama" or AI_PROVIDER == "none"),
            "model": GEMINI_MODEL if AI_PROVIDER == "gemini" else os.getenv("OLLAMA_MODEL", "gemma3"),
        },
'''
if old in s:
    s=s.replace(old,new,1)

p.write_text(s, encoding="utf-8")
print("ApplyBot production discovery/AI patch applied")
