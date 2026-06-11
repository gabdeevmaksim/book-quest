#!/usr/bin/env python3
"""Headless test harness for Quest Book v3 — stateful policies, heroic-route stress test."""
import json, random, sys
from collections import defaultdict, deque
from itertools import product

if len(sys.argv) < 2:
    sys.exit("usage: playtest.py stories/<story>.json [easy|normal|hard]")
STORY = sys.argv[1]
DIFF  = sys.argv[2].lower() if len(sys.argv) > 2 else None   # easy | normal | hard
# expected (cautious win %, heroic death %) bands per difficulty tier
BANDS = {
    "easy":   {"cautious_win": (93, 100), "heroic_death": (0, 12)},
    "normal": {"cautious_win": (85, 99),  "heroic_death": (12, 35)},
    "hard":   {"cautious_win": (60, 88),  "heroic_death": (30, 75)},
}
story = json.load(open(STORY))
locs  = story["locations"]; items = story.get("items", {})
tmpl  = story["character_template"]; START = story["start_location_id"]
ATTRS = ["strength","agility","stamina"]
def coerce(v): return [] if v is None else (v if isinstance(v,list) else [v])
def _bad_end(t):
    """A deliberately-signposted non-victory ending — a reading player avoids it."""
    L=locs.get(t,{}); return bool(L.get("is_end")) and not L.get("is_victory",True)
def dice_dist(dt):
    n,s=map(int,dt.split("d")); d=defaultdict(int)
    for c in product(range(1,s+1),repeat=n): d[sum(c)]+=1
    return {k:v/s**n for k,v in d.items()},n,s
def p_at_least(dt,need):
    dist,_,_=dice_dist(dt); return sum(p for k,p in dist.items() if k>=need)
def p_pass_fixed(a,cv,dt): return p_at_least(dt,cv-a)
def max_roll(dt): _,n,s=dice_dist(dt); return n*s

# ── quick check-difficulty table (pass odds at average rolled stat 7) ──
print("="*72); print("  CHECK DIFFICULTY  (pass odds; attr=avg 7, +1d6)"); print("="*72)
for lid,loc in locs.items():
    for ch in loc.get("choices",[]):
        if "condition" in ch:
            c=ch["condition"]; cv=c["check_value"]; dt=c.get("dice_type","1d6"); at=c["attribute"]
            ib=c.get("item_bonus")
            p10=p_pass_fixed(7,cv,dt)
            extra=f"  (+{ib['bonus']} {ib['item']} -> {p_pass_fixed(7+ib['bonus'],cv,dt):.0%})" if ib else ""
            print(f"  {lid:18s} {at[:3].upper()} DC{cv:<2} fail-{c.get('fail_damage',2)}  ~{p10:.0%}{extra}  :: {ch['text'][:42]}")
for lid,loc in locs.items():
    if "monster" in loc:
        m=loc["monster"]; print(f"  {lid:18s} {m.get('attribute','strength')[:3].upper()} DC{m['strength']:<2} fail-{m['fail_damage']}  ~{p_pass_fixed(7,m['strength'],m.get('dice_type','1d6')):.0%}  :: MONSTER {m['name']}")

# ── reachability + min-stat (best-case) completability ──
seen=set(); q=deque([(START,frozenset())]); endings=set(); reach=set(); broken=[]
while q:
    lid,inv=q.popleft()
    if (lid,inv) in seen: continue
    seen.add((lid,inv)); reach.add(lid); loc=locs.get(lid)
    if loc is None: broken.append(lid); continue
    inv2=set(inv); inv2.update(loc.get("loot",[]))
    if loc.get("is_end"): endings.add(lid); continue
    for ch in loc.get("choices",[]):
        if ch.get("requires_item") and ch["requires_item"] not in inv2: continue
        t=ch.get("target_id"); ni=set(inv2); ni.update(coerce(ch.get("gives_item")))
        if t: q.append((t,frozenset(ni)))
        ft=ch.get("fail_target") or ch.get("condition",{}).get("fail_target")
        if ft: q.append((ft,frozenset(inv2)))
allend={l for l,v in locs.items() if v.get("is_end")}
print(f"\n  reachability: {len(reach)}/{len(locs)} locs, {len(endings)}/{len(allend)} endings, broken={broken or 'none'}")

# ── Monte Carlo ──
def roll(dt): n,s=map(int,dt.split("d")); return sum(random.randint(1,s) for _ in range(n))
def play(policy,max_steps=400):
    attr={a:roll("2d6") for a in ATTRS}; mhp=tmpl["health"]; hp=mhp; loc=START
    inv=[]; looted=set(); defeated=set(); steps=0; mn=hp
    while steps<max_steps:
        steps+=1; L=locs.get(loc)
        if L is None: return ("CRASH",loc,hp,mn)
        if loc not in looted:
            for it in L.get("loot",[]):
                if it not in inv: inv.append(it)
            if L.get("loot"): looted.add(loc)
        if hp<=0: return ("DEATH",loc,hp,mn)
        if L.get("is_end"): return ("WIN" if L.get("is_victory",True) else "BADEND",loc,hp,mn)
        heals=[("use",it) for it in inv if items.get(it,{}).get("use",{}).get("heal")] if hp<mhp else []
        if "monster" in L and loc not in defeated:
            acts=[("fight",None)]+[("flee",c) for c in L.get("choices",[]) if c.get("is_flee")]+heals
        else:
            acts=[("choice",c) for c in L.get("choices",[]) if not c.get("is_flee")
                  and not (c.get("requires_item") and c["requires_item"] not in inv)]+heals
        if not acts: return ("STUCK",loc,hp,mn)
        kind,ch=policy(loc,L,acts,hp,mhp,attr,inv)
        if kind=="use": hp=min(mhp,hp+items[ch]["use"]["heal"]); inv.remove(ch)
        elif kind=="fight":
            m=L["monster"]; a=m.get("attribute","strength")
            if roll(m.get("dice_type","1d6"))+attr[a]>=m["strength"]: defeated.add(loc)
            else: hp-=m.get("fail_damage",4)
        else:
            c=ch
            if "condition" in c:
                cc=c["condition"]; b=0; ib=cc.get("item_bonus")
                if ib and ib.get("item") in inv: b=ib.get("bonus",0)
                if roll(cc.get("dice_type","1d6"))+attr[cc["attribute"]]+b>=cc["check_value"]:
                    loc=c["target_id"]
                    for it in coerce(c.get("gives_item")):
                        if it not in inv: inv.append(it)
                else:
                    hp-=cc.get("fail_damage",2)
                    ft=c.get("fail_target") or cc.get("fail_target")
                    if ft: loc=ft
            else:
                loc=c["target_id"]
                for it in coerce(c.get("gives_item")):
                    if it not in inv: inv.append(it)
        mn=min(mn,hp)
    return ("LOOP",loc,hp,mn)

def make_random():
    def pol(loc,L,acts,hp,mhp,attr,inv): return random.choice(acts)
    return pol
def make_smart():
    vis=defaultdict(int)
    def pol(loc,L,acts,hp,mhp,attr,inv):
        vis[loc]+=1
        heals=[a for a in acts if a[0]=="use"]
        if heals and hp<=0.4*mhp: return heals[0]
        fights=[a for a in acts if a[0]=="fight"]; flees=[a for a in acts if a[0]=="flee"]
        if fights:
            m=L["monster"]; a=m.get("attribute","strength")
            p=p_pass_fixed(attr[a],m["strength"],m.get("dice_type","1d6"))
            if p<0.5 or hp<=m.get("fail_damage",4):
                cand=[]
                for f in flees:
                    c=f[1]; cc=c.get("condition")
                    fp=p_pass_fixed(attr[cc["attribute"]],cc["check_value"],cc.get("dice_type","1d6")) if cc else 1.0
                    cand.append((fp,f))
                if cand: return max(cand,key=lambda x:x[0])[1]
            return fights[0]
        def score(a):
            if a[0]=="use": return -1
            c=a[1]
            if _bad_end(c.get("target_id")): return -999   # never walk into a doom ending
            if "condition" not in c: base=1.0
            else:
                cc=c["condition"]; b=0; ib=cc.get("item_bonus")
                if ib and ib.get("item") in inv: b=ib.get("bonus",0)
                base=p_pass_fixed(attr[cc["attribute"]]+b,cc["check_value"],cc.get("dice_type","1d6"))
            return base - 0.25*vis.get(c.get("target_id"),0) + random.random()*1e-3
        return max(acts,key=score)
    return pol
def make_heroic():
    """Theme-agnostic 'commits to the dangerous content' player: always fights,
    prefers risky (checked) and unexplored choices, and only accepts an ending
    once fresh risky options run out. Heals only when badly hurt."""
    vis=defaultdict(int)
    def pol(loc,L,acts,hp,mhp,attr,inv):
        vis[loc]+=1
        heals=[a for a in acts if a[0]=="use"]
        if heals and hp<=0.45*mhp: return heals[0]
        fights=[a for a in acts if a[0]=="fight"]
        if fights: return fights[0]                       # never flee a fight
        choices=[a for a in acts if a[0]=="choice"]
        if not choices:
            fl=[a for a in acts if a[0]=="flee"]; return random.choice(fl or acts)
        def score(a):
            c=a[1]; t=c.get("target_id","")
            s=2.0*vis.get(t,0)                            # avoid re-treading (grows)
            if "condition" not in c: s+=1.0               # prefer risky over safe
            if locs.get(t,{}).get("is_end"): s+=3.0       # delay endings, but not forever
            if _bad_end(t): s+=100.0                      # a hero doesn't pick the doom ending
            return s+random.random()*0.01
        return min(choices,key=score)
    return pol

import os
N=int(os.environ.get("QUEST_PLAYTEST_N", 20000))
print("\n"+"="*72); print(f"  MONTE CARLO  n={N} per policy  (random stats 2d6, random dice)"); print("="*72)
print("  policy   |  WIN   DEATH  LOOP  STUCK |  avgHP@win  lowestHP@win | endings")
metrics={}
for name,mk in [("random ",make_random),("cautious",make_smart),("heroic ",make_heroic)]:
    res=defaultdict(int); hpsum=0; mnsum=0; wins=0; endc=defaultdict(int)
    for _ in range(N):
        out,loc,hp,mn=play(mk()); res[out]+=1
        if out=="WIN": wins+=1; hpsum+=hp; mnsum+=mn; endc[loc]+=1
    w=res["WIN"]/N*100; d=res["DEATH"]/N*100; lp=res["LOOP"]/N*100; sk=res["STUCK"]/N*100
    ah=hpsum/wins if wins else 0; am=mnsum/wins if wins else 0
    metrics[name.strip()]={"win":w,"death":d,"loop":lp,"stuck":sk}
    top=sorted(endc.items(),key=lambda x:-x[1])
    eshort=", ".join(f"{k.replace('_ending','').replace('_',' ')}:{v*100//N}%" for k,v in top)
    print(f"  {name} | {w:5.1f}% {d:5.1f}% {lp:4.1f}% {sk:4.1f}% |   {ah:4.1f}/{tmpl['health']}    {am:5.1f}     | {eshort}")

# ── structural red flags (independent of difficulty) ──
flags=[]
if metrics["random"]["loop"]+metrics["cautious"]["loop"]+metrics["heroic"]["loop"]>1.0: flags.append("LOOP>1% — possible safe cycle with no progress")
if metrics["cautious"]["stuck"]+metrics["heroic"]["stuck"]>0.2: flags.append("STUCK>0.2% — a location with no usable action (soft-lock)")
if flags:
    print("\n  ⚠ structural flags: " + "; ".join(flags))

# ── difficulty verdict ──
if DIFF in BANDS:
    b=BANDS[DIFF]; cw=metrics["cautious"]["win"]; hd=metrics["heroic"]["death"]
    cw_ok=b["cautious_win"][0]<=cw<=b["cautious_win"][1]
    hd_ok=b["heroic_death"][0]<=hd<=b["heroic_death"][1]
    print("\n"+"="*72); print(f"  DIFFICULTY VERDICT  vs target '{DIFF}'"); print("="*72)
    print(f"  cautious win   {cw:5.1f}%   target {b['cautious_win'][0]:>3}-{b['cautious_win'][1]:<3}%   {'OK' if cw_ok else 'ADJUST'}")
    print(f"  heroic death   {hd:5.1f}%   target {b['heroic_death'][0]:>3}-{b['heroic_death'][1]:<3}%   {'OK' if hd_ok else 'ADJUST'}")
    if not cw_ok and cw<b["cautious_win"][0]: print("   hint: too deadly for careful play — raise health or lower some DCs/fail_damage.")
    if not cw_ok and cw>b["cautious_win"][1]: print("   hint: too soft — raise climactic DCs / fail_damage, or lower health.")
    if not hd_ok and hd<b["heroic_death"][0]: print("   hint: heroic routes lack stakes — raise monster/vault DCs & fail_damage.")
    if not hd_ok and hd>b["heroic_death"][1]: print("   hint: heroic routes too lethal — lower fail_damage, or add a heal item / retreat.")
    ok = cw_ok and hd_ok and not flags
    print(f"\n  >>> {'PASS — balance matches difficulty' if ok else 'ADJUST — nudge the knobs above and re-run'}")
    sys.exit(0 if ok else 2)
elif DIFF:
    print(f"\n  (unknown difficulty '{DIFF}'; use easy | normal | hard for a verdict)")
