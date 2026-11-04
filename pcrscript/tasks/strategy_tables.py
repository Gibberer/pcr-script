"""Parse simple five-avatar guide tables; unsupported layouts remain unknown."""
from pathlib import Path
import json
import re
import cv2 as cv
import numpy as np
import requests
from ..game_ui.avatars import AvatarIndex,face_crop,feature
from ..game_ui.screen import normalized, ocr_engine
from ..run_session import atomic_json


def universal_row(image,ocr,index):
    result=ocr(image)
    for spacing in ('median','first','minimum'):
        row=_universal_row(image,result,index,spacing)
        if row is not None:return row
    return None


def _universal_row(image,result,index,spacing):
    if result.txts is None:return None
    labels=[(normalized(text),box) for text,box,score in zip(result.txts,result.boxes,result.scores)
            if normalized(text) in ('一队通用','前三章') and score>.9]
    if len(labels)!=1:return None
    label,box=labels[0];box=np.asarray(box);cy=int(box[:,1].mean());start=int(box[:,0].max())+3
    hsv=cv.cvtColor(image,cv.COLOR_BGR2HSV)
    mask=((hsv[max(0,cy-20):cy+20,:,1]>45)&(hsv[max(0,cy-20):cy+20,:,2]>45)).mean(0)>.15
    mask[:start]=False
    mask=cv.morphologyEx(mask.astype(np.uint8)[None,:],cv.MORPH_CLOSE,np.ones((1,3),np.uint8))[0]
    edges=np.diff(np.r_[0,mask,0].astype(int))
    runs=[(int(x),int(z)) for x,z in zip(np.where(edges==1)[0],np.where(edges==-1)[0]) if z-x>24]
    if len(runs)<3:return None
    gaps=[runs[k+1][0]-runs[k][0] for k in range(min(4,len(runs)-1))]
    step=round(float(np.median(gaps)) if spacing=='median' else (runs[2][0]-runs[0][0])/2 if spacing=='first' else min(gaps))
    size=round(step*.92)
    if not 28<=size<=130:return None
    x=runs[0][0];y=cy-size//2
    names=[];proof=[];elements=[];stars=[]
    for j in range(5):
        rects=[(x+j*step+dx,y+dy,size+ds,size+ds) for dx in (-2,-1,0,1,2) for dy in (-2,-1,0,1,2) for ds in (-2,-1,0,1,2)]
        vectors=np.stack([feature(face_crop(image,r)) for r in rects])
        scores=(vectors@index.matrix.T).max(axis=0)
        ranked=[]
        for i in np.argsort(scores)[::-1]:
            name=str(index.names[i])
            if name not in [n for n,_ in ranked]:ranked.append((name,float(scores[i])))
            if len(ranked)==2:break
        if len(ranked)<2 or ranked[0][1]<.93 or ranked[0][1]-ranked[1][1]<.025 or ranked[0][0].startswith('unit:'):
            return None
        names.append(ranked[0][0]);proof.append(ranked)
        badge=max(6,round(size*.18))
        patch=hsv[y+size-badge:y+size-1,x+j*step+size-badge:x+j*step+size-1]
        colorful=patch[(patch[:,:,1]>100)&(patch[:,:,2]>100)]
        if not len(colorful):return None
        hue=float(np.median(colorful[:,0]))
        elements.append('fire' if hue<12 or hue>172 else 'light' if hue<35 else 'wind' if hue<85 else 'water' if hue<125 else 'dark')
        corner_size=max(8,round(size*.24));corner=hsv[y+size-corner_size:y+size,x+j*step:x+j*step+corner_size]
        stars.append(6 if np.mean((corner[:,:,0]>140)&(corner[:,:,0]<175)&(corner[:,:,1]>80))>.2 else None)
    if len(set(names))!=5 or len(set(elements))!=1:return None
    flags=[normalized(t).upper().replace('0','O') for t,b in zip(result.txts,result.boxes)
           if np.asarray(b)[:,0].mean()>x+4.5*step and abs(np.asarray(b)[:,1].mean()-cy)<size*.4
           and re.fullmatch('[OX0ox]{5}',normalized(t))]
    if len(flags)!=1:
        full=[t for t,b in zip(result.txts,result.boxes) if normalized(t)=='全SET'
              and x+4.5*step<np.asarray(b)[:,0].mean()<x+8*step
              and abs(np.asarray(b)[:,1].mean()-cy)<size*.4]
        if len(full)!=1:return None
        flags=['OOOOO']
    notes='\n'.join(t for t,b in zip(result.txts,result.boxes)
                    if np.asarray(b)[:,0].mean()>x+5*step and abs(np.asarray(b)[:,1].mean()-cy)<size)
    return dict(element=elements[0],names=names,required_stars=stars,confidence=proof,
                instant=[c=='O' for c in flags[0]],scope='universal_row',build_basis='source_members_local_build',
                chapters=[1,3] if label=='前三章' else None,notes=notes,
                excluded_stages=re.findall(r'\d+-\d+',notes),
                pending=['表格未提供完整专武开关/培养要求，按授权的本地培养试验；不是完整攻略复现'])


def board_seeds(image):
    """Rows of equal, adjacent card outlines; edges can merge, so two neighbours are enough."""
    edges=cv.Canny(cv.cvtColor(image,cv.COLOR_BGR2GRAY),40,100)
    contours,_=cv.findContours(edges,cv.RETR_LIST,cv.CHAIN_APPROX_SIMPLE)
    boxes=sorted({cv.boundingRect(c) for c in contours},key=lambda b:b[1])
    boxes=[b for b in boxes if 40<=b[2]<=120 and .7*b[2]<=b[3]<=1.4*b[2]]
    rows=[]
    for box in boxes:
        row=next((r for r in rows if abs(r[0][1]-box[1])<=6),None)
        if row is None:rows.append([box])
        else:row.append(box)
    seeds=[]
    for row in rows:
        row.sort()
        # Anchor on each adjacent pair: a stray outline can share the row but not the grid.
        for a,b in zip(row,row[1:]):
            if .85*min(a[2],b[2])<=b[0]-a[0]<=1.2*max(a[2],b[2]):
                # A taller outline includes the cell's frame; the square card sits at its centre.
                seed=(a[0],a[1]+max(0,a[3]-a[2])//2,b[0]-a[0])
                if not any(abs(seed[1]-s[1])<=6 and abs(seed[2]-s[2])<=3 and (seed[0]-s[0])%s[2] in range(-4,5) for s in seeds):
                    seeds.append(seed)
    return seeds


def board_cell(image,x,y,step,index):
    """The best-aligned identity of one card, or None when its face is not clear.

    Empty cells reach high scores with a margin near .01, so a clear read needs real
    separation; a weaker score must separate further than a costume sibling would.
    """
    sizes=range(round(step*.84),round(step*1.02)+1,2)
    rects=[(x+dx,y+dy,size,size) for dx in range(-6,7,2) for dy in range(-6,7,2) for size in sizes]
    rects=[r for r in rects if r[0]>=0 and r[1]>=0 and r[0]+r[2]<=image.shape[1] and r[1]+r[3]<=image.shape[0]]
    if not rects:return None
    scores=np.stack([feature(face_crop(image,r)) for r in rects])@index.matrix.T
    chosen=int(scores.max(axis=1).argmax());row=scores[chosen]
    ranked={}
    for i in np.argsort(row)[::-1]:
        ranked.setdefault(str(index.names[i]),float(row[i]))
        if len(ranked)==2:break
    if len(ranked)<2:return None
    (name,score),(_,second)=ranked.items()
    if name.startswith('unit:') or score<.85 or score-second<(.03 if score>=.9 else .05):return None
    return dict(name=name,score=score,margin=score-second,rectangle=list(rects[chosen]))


def board_set(texts,row,others):
    """The team's first standalone five-letter SET; a timed axis has none and stays unread."""
    left=row['rectangle'][0]+row['rectangle'][2]
    top=row['rectangle'][1]
    right=min([o['x'] for o in others if o['x']>=left and abs(o['y']-top)<=row['step']*.5],default=1e9)
    bottom=min([o['y'] for o in others if o['y']>top+row['step']*.5 and o['x']<left<o['x']+o['step']*6],default=1e9)
    flags=[t for t in texts if left<=t.center[0]<right and top<=t.center[1]<bottom
           and re.fullmatch('[OX]{5}',normalized(t.text).upper().replace('0','O').replace('×','X').replace('〇','O'))]
    if not flags:return None
    first=min(flags,key=lambda t:t.center[1]).text
    return [c=='O' for c in normalized(first).upper().replace('0','O').replace('×','X').replace('〇','O')]


def board_reference_cell(text):
    """A bare column label or value records the author's account; a sentence can still require something."""
    return bool(re.fullmatch(r'(?:Rank|R)?\d+[-－][0-6]|MP\d+|属性等级|属性技能|公主骑士(?:等级|技能)?|大师(?:点|等级|技能)?|'
                             r'职能精通|职阶专精|全职业|特别装备|特装|粉装|突破|满装',normalized(text),re.I))


def board_hint(texts):
    """Grid search is slow; only frames that read like a board or a SET list are worth it."""
    return any(re.fullmatch('[OX0○〇×]{5}',normalized(t.text).upper()) or normalized(t.text).upper() in ('RANK','备注','星级','职阶专精')
               for t in texts)


def guide_board_rows(image,texts,index):
    """Read a static guide board: rows of five portrait cells, each with an optional SET note.

    Small table portraits score below in-game cards, so this only nominates rosters. A free
    simulation still decides whether they spend anything.
    """
    if not index.names:return []
    found={}
    seeds=board_seeds(image)
    # Merged outlines can misjudge one pair's spacing; a board's tables share one grid.
    attempts={(x0,y,step) for x0,y,own in seeds for step in {s[2] for s in seeds}|{own} if abs(step-own)<=own*.12}
    # A header can merge the first or last row's outlines; extend a stack by its own row gap.
    for x0,y,step in seeds:
        stack=sorted(s[1] for s in seeds if abs(s[0]-x0)<=6 and abs(s[2]-step)<=5)
        if len(stack)>=2:
            attempts|={(x0,stack[0]-(stack[1]-stack[0]),step),(x0,stack[-1]+(stack[-1]-stack[-2]),step)}
    for x0,y,step in sorted(attempts):
        columns=sorted({x0+k*step for k in range(-8,12) if 0<=x0+k*step<=image.shape[1]-step})
        run=[]
        for x in columns+[None]:
            cell=None if x is None else board_cell(image,x,y,step,index)
            if cell is not None:
                run.append(cell);continue
            names=[c['name'] for c in run]
            if len(run)==5 and len(set(names))==5:
                first=run[0]['rectangle']
                # Neighbouring seeds can read one row twice; the better-aligned reading stays.
                key=tuple(names)
                total=sum(c['score'] for c in run)
                if key not in found or total>found[key]['total']:
                    found[key]=dict(names=names,members=run,x=first[0],y=first[1],step=step,total=total,
                        rectangle=[first[0],first[1],run[-1]['rectangle'][0]+run[-1]['rectangle'][2]-first[0],step])
            run=[]
    rows=list(found.values())
    for row in rows:
        row['instant']=board_set(texts,row,[o for o in rows if o is not row])
    return sorted(rows,key=lambda r:(r['y'],r['x']))


def extract_tables(source,api,*,directory='cache/game/strategies/video_tables'):
    if source.get('provider')!='bilibili':return {'parties':[],'pending':['该来源尚无可用的配队表解析器']}
    bvid=source['bvid'];root=Path(directory)/bvid;root.mkdir(parents=True,exist_ok=True)
    saved=root/'tables.json'
    if saved.exists():
        value=json.loads(saved.read_text(encoding='utf-8'))
        if value.get('version')==5:return value
    parties=[];ocr=ocr_engine();index=AvatarIndex()
    if not index.names:return {'parties':[],'pending':['头像索引为空，不能猜测视频角色']}
    pages=sorted(source['pages'][:3],key=lambda p:int(re.match(r'(\d+)',p.get('part',''))[1]) if re.match(r'(\d+)',p.get('part','')) else 0)
    for page in pages:
        if len({p['element'] for p in parties})==5:break
        cid=page['cid'];video=root/f'{cid}.mp4'
        if not video.exists():
            data=api.getVideoPlay(cid=cid,bvid=bvid,qn=64).get('data',{})
            media=(data.get('durl') or [{}])[0]
            for url in [media.get('url')]+media.get('backup_url',[]):
                if not url:continue
                try:
                    r=requests.get(url,headers={'Referer':source['url'],'User-Agent':'Mozilla/5.0'},timeout=40)
                    r.raise_for_status();video.write_bytes(r.content);break
                except requests.RequestException:continue
        if not video.exists():continue
        capture=cv.VideoCapture(str(video));seen={}
        for seconds in range(5,min(int(page.get('duration',0)),360),10):
            capture.set(cv.CAP_PROP_POS_MSEC,seconds*1000);ok,frame=capture.read()
            if not ok:continue
            if frame.shape[0]!=720:frame=cv.resize(frame,(round(frame.shape[1]*720/frame.shape[0]),720))
            row=universal_row(frame,ocr,index)
            if row is None:continue
            key=(row['element'],tuple(row['names']))
            seen[key]=seen.get(key,0)+1
            if seen[key]!=2:continue
            evidence=root/f'{cid}_{seconds}.png';cv.imencode('.png',frame)[1].tofile(evidence)
            chapters=re.search(r'(\d+)\s*[-～~至]\s*(\d+)图',source['title'])
            row.update(source=source['url'],cid=cid,seconds=seconds,evidence=str(evidence),
                       chapters=row.get('chapters') or ([int(chapters[1]),int(chapters[2])] if chapters else None))
            parties.append(row)
            print('[攻略表格] 已核验通用队：'+row['element'],flush=True)
            if row.get('chapters')==[1,3]:break
        capture.release()
    value=dict(version=5,source=source['url'],parties=parties,pending=[] if parties else ['未解析到两帧一致的五人通用配队表'])
    if parties:atomic_json(saved, value)
    return value
