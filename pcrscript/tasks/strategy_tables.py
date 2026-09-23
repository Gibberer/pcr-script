"""Parse simple five-avatar guide tables; unsupported layouts remain unknown."""
from pathlib import Path
import json
import re
import cv2 as cv
import numpy as np
import requests
from rapidocr import RapidOCR
from ..game_ui.avatars import AvatarIndex,face_crop,feature
from ..game_ui.screen import normalized


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


def extract_tables(source,api,*,directory='cache/game/strategies/video_tables'):
    if source.get('provider')!='bilibili':return {'parties':[],'pending':['该来源尚无可用的配队表解析器']}
    bvid=source['bvid'];root=Path(directory)/bvid;root.mkdir(parents=True,exist_ok=True)
    saved=root/'tables.json'
    if saved.exists():
        value=json.loads(saved.read_text(encoding='utf-8'))
        if value.get('version')==5:return value
    parties=[];ocr=RapidOCR();index=AvatarIndex()
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
    if parties:saved.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    return value
