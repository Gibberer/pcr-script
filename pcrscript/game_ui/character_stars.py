"""Opt-in five-star upgrades with verified identity and item/currency receipts."""
import re
import sqlite3
from contextlib import closing
import cv2 as cv
import numpy as np
from .character_equipment import open_character_memory
from .screen import EventUIError,normalized


def unlocked_stars(screen):
    hsv=cv.cvtColor(screen.image,cv.COLOR_BGR2HSV)
    count=0
    for x in (171,212,253,294,335):
        patch=hsv[318:350,x-12:x+12]
        colored=(patch[:,:,1]>100)&(patch[:,:,2]>160)
        gold=np.mean((patch[:,:,0]>12)&(patch[:,:,0]<38)&colored)
        blue=np.mean((patch[:,:,0]>90)&(patch[:,:,0]<125)&colored)
        count+=gold>.3 or blue>.3
    return int(count)


def active_stars(screen):
    hsv=cv.cvtColor(screen.image,cv.COLOR_BGR2HSV)
    return sum(float(np.mean((hsv[318:350,x-12:x+12,0]>12)&(hsv[318:350,x-12:x+12,0]<38)
                             &(hsv[318:350,x-12:x+12,1]>100)&(hsv[318:350,x-12:x+12,2]>160)))>.3
               for x in (171,212,253,294,335))


def number(screen,roi):
    item=screen.find(r'[\d,]+',roi,exact=True)
    return int(normalized(item.text).replace(',','')) if item else None


def star_confirmation_ready(screen,required):
    """Check the exact cost and unlabeled shard icon on the final dialog."""
    cost=number(screen,(175,260,250,305))
    balance=number(screen,(315,260,420,305))
    # OCR may insert a dot between the icon's multiplication sign and amount
    # (observed as ×.150); the exact required integer must still match.
    material=screen.find(r'[×x][.·]?'+str(required),(55,355,150,415),exact=True)
    return bool(screen.find('消耗玛那',(45,250,155,310),exact=True)
                and screen.find('必要道具',(45,295,160,335),exact=True)
                and material and cost is not None and balance is not None
                and 0<cost<=balance
                and screen.blue_button(screen.find('才能开花',(480,445,710,510),exact=True)))


def star_result_step(screen):
    if screen.find('开花完成',(300,345,660,455),exact=True):
        return 'animation'
    if screen.find('才能开花完毕',(250,15,720,75),exact=True):
        button=screen.find('确认',(350,445,620,510),exact=True)
        return button if button else None
    return None


def purchase_receipt(screen,name,amount,cost,before,owned,read_small=None):
    if not screen.find('购买完毕',(250,105,710,175),exact=True):
        raise EventUIError('女神秘石购买完成标题未知')
    if not screen.find(r'消耗女神的秘石[×x]'+str(cost),(360,180,590,225)):
        raise EventUIError('女神秘石购买回执价格不符')
    if not screen.find(re.escape(normalized(name)+'的记忆碎片')+r'[×x]'+str(amount),(300,205,670,245)):
        raise EventUIError('女神秘石购买回执角色或数量不符')
    held_before=number(screen,(515,250,570,285))
    if held_before is None and read_small is not None:
        held_before=read_small(screen,(530,255,560,280))
    values=(held_before,number(screen,(640,250,705,285)),
            number(screen,(480,285,580,325)),number(screen,(620,285,710,325)))
    if values!=(owned,owned+amount,before,before-cost):
        raise EventUIError('女神秘石购买回执碎片或余额变化不符')
    return dict(owned_after=values[1],after=values[3])


def five_star_shards(name,stars,owned,next_required,database='cache/redive_cn.db'):
    stars=int(stars)
    with closing(sqlite3.connect(database)) as connection:
        ids=[uid for uid,n in connection.execute('SELECT unit_id,unit_name FROM unit_data') if normalized(n)==normalized(name)]
        if len(ids)!=1:raise EventUIError('五星碎片需求无法唯一匹配角色')
        rows=dict(connection.execute('SELECT rarity,consume_num FROM unit_rarity WHERE unit_id=? AND rarity>? AND rarity<=5',(ids[0],stars)))
    if set(rows)!=set(range(stars+1,6)) or rows[stars+1]!=next_required:
        raise EventUIError('数据库升星碎片需求与当前页面不符')
    return max(0,sum(rows.values())-owned)


def buy_shards(ui,name,missing,report,save,allow_amulets):
    if not allow_amulets:
        raise EventUIError('升星碎片不足，女神秘石兑换未授权')
    ui.expect_click('获取方法',(480,400,700,475),exact=True)
    ui.wait(lambda s:s.find('记忆碎片获取方法',(250,0,720,75),exact=True),'碎片获取方法')
    ui.expect_click('女神的秘石商店',(260,285,690,365),exact=True)
    ui.wait(lambda s:s.find('商店',(40,0,200,65),exact=True),'秘石商店')
    for batch in range(20):
        s=ui.capture()
        # Filter the shop by the exact base name, then verify the outfit on
        # the purchase dialog before touching its confirmation button.
        ui.click((748,438));ui.click((510,438));ui.driver.input(normalized(name).split('(')[0])
        from ..run_session import clock as time
        time.sleep(1);ui.click((210,440));s=ui.capture()
        candidates=[]
        for x in (330,500,670,840):
            title=normalized(s.text((x-75,205,x+75,248)))
            if normalized(name) in title:candidates.append(x)
        if len(candidates)!=1:raise EventUIError('秘石商店未唯一匹配所需衣装，未购买')
        ui.click((candidates[0],344))
        s=ui.wait(lambda s:s.find('购买确认',(250,0,720,75),exact=True),'碎片购买预览')
        if not s.find(re.escape(normalized(name)+'的记忆碎片'),(250,95,710,150),exact=True):
            raise EventUIError('碎片购买角色不符，未购买')
        before=number(s,(630,332,705,369))
        # Full-frame OCR omits a lone one-digit inventory value. Restrict the
        # retry to the confirmed numeric field, away from the 持有数 label.
        owned=number(s,(630,248,705,286))
        if owned is None:owned=ui.number(s,(675,254,700,279))
        if before is None or owned is None:raise EventUIError('秘石余额或碎片持有数不明确')
        ui.expect_click('MAX',(590,285,700,335),exact=True);s=ui.capture()
        amount=number(s,(440,290,520,329))
        if amount is None:raise EventUIError('购买数量无法确认')
        if amount>missing:
            # MAX may show the game's five-star quantity cap. Only accept
            # an explicit cap explanation; never buy an unchecked excess.
            text=normalized(s.text())
            if re.search(r'(?:五星|5星|★5)',text) and re.search(r'只需|需要|足够',text):
                ui.save('five_star_quantity_cap',s)
                ui.expect_click('确认',(480,430,710,520),exact=True)
                s=ui.capture();amount=number(s,(440,290,520,329))
        cost=number(s,(420,332,480,369))
        if amount is None or not 1<=amount<=missing or cost is None or not 0<cost<=before:
            raise EventUIError('碎片数量/总价/余额校验未通过')
        purchase=dict(name=name,amount=amount,cost=cost,before=before,owned_before=owned,status='pending',
                      evidence=str(ui.save('purchase_'+str(batch),s)))
        report['purchases'].append(purchase);save()
        ui.expect_click('确认',(480,450,700,510),exact=True)
        s=ui.wait(lambda s:s.find('购买完毕',(250,105,710,175),exact=True),'秘石购买回执')
        receipt=purchase_receipt(s,name,amount,cost,before,owned,ui.number)
        purchase.update(status='confirmed',**receipt,evidence_after=str(ui.save('purchased_'+str(batch),s)))
        save();missing-=amount
        ui.expect_click('确认',(370,340,585,410),exact=True)
        ui.wait(lambda frame:frame.find('商店',(40,0,200,65),exact=True),'返回秘石商店')
        if missing==0:return
    raise EventUIError('碎片兑换达到分批保护上限')


def upgrade_to_five(ui,name,report,save,*,allow_amulets=False):
    report.update(name=name,purchases=[],upgrades=[],status='checking');save()
    for step in range(5):
        s=open_character_memory(ui,name)
        if s is None:raise EventUIError('培养页面未确认角色衣装')
        stars=unlocked_stars(s)
        if stars==5:
            # Blue stars are already unlocked but currently reduced by ★变更.
            current=active_stars(s)
            if current<5:
                ui.click((34,98))
                dialog=ui.wait(lambda frame:frame.find('★变更确认',(250,0,710,75),exact=True),'星级变更')
                if not dialog.find('现在的★',(250,95,400,140),exact=True):
                    raise EventUIError('星级变更弹窗内容未知')
                ui.click((780,146));dialog=ui.capture()
                button=dialog.find('变更',(480,450,710,515),exact=True)
                if not dialog.blue_button(button):raise EventUIError('五星星级变更按钮不可用')
                record=dict(before=current,target=5,status='pending',evidence=str(ui.save('five_star_change',dialog)))
                report['upgrades'].append(record);save()
                ui.click(button)
                ui.wait(lambda frame:frame.find('角色强化',(40,0,250,65),exact=True)
                        and active_stars(frame)==5,'星级设置完成')
                record['status']='confirmed';save()
            report.update(status='complete',target=5);save();return
        if not 1<=stars<5:raise EventUIError('当前解锁星级无法确认，未升星')
        fraction=s.find(r'\d+/\d+',(710,253,835,293),exact=True)
        if fraction is None:raise EventUIError('升星所需碎片数量未知')
        owned,required=map(int,normalized(fraction.text).split('/'))
        if owned<required:
            needed=five_star_shards(name,stars,owned,required)
            buy_shards(ui,name,needed,report,save,allow_amulets)
            s=open_character_memory(ui,name)
            fraction=s.find(r'\d+/\d+',(710,253,835,293),exact=True) if s else None
            if fraction is None or int(normalized(fraction.text).split('/')[0])<required:
                raise EventUIError('碎片购买后持有数量未确认，未升星')
        before=str(ui.save(f'star_{stars}_before',s));ui.expect_click('才能开花',(700,400,930,475),exact=True)
        s=ui.wait(lambda s:s.find('才能开花确认|才能开花',(250,0,720,75)), '升星确认')
        # The exact final confirmation layout must show a single next-star
        # upgrade and resource cost; unfamiliar dialogs remain stopped.
        # The material icon has no OCR label on this confirmation page.  The
        # game prints only “×120” below it; compare that with the requirement
        # read on the character page immediately before opening the dialog.
        if not star_confirmation_ready(s,required):
            raise EventUIError('升星确认材料未完整显示，保留现场')
        record=dict(before=stars,target=stars+1,evidence=before,status='pending')
        report['upgrades'].append(record);save()
        ui.expect_click('确认|才能开花',(480,430,720,520),exact=True)
        animation_closed=False
        result_closed=False
        def close(frame):
            nonlocal animation_closed,result_closed
            action=star_result_step(frame)
            if action=='animation' and not animation_closed:
                animation_closed=True
                ui.click((480,420))
            elif action is not None and action!='animation' and not result_closed:
                result_closed=True
                ui.click(action)
        ui.wait(lambda s:s.find('角色强化',(40,0,250,65),exact=True) and unlocked_stars(s)==stars+1,
                '升星结果',timeout=60,handle=close)
        record['status']='confirmed';save()
    raise EventUIError('升至5星步骤超出边界')
