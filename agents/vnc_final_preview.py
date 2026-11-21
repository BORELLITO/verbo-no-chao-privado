"""Prévia de final de cinema com camadas de luz FILMADAS (Mixkit, licença gratuita verificada). Somente prévia: nao altera o motor nem o style lock.
Roda no GitHub (o ambiente do assistente nao alcanca o Mixkit). Saida: /tmp/preview_out (mp4 meia-resolucao + tira de quadros) e base64 no log."""
import os, json, subprocess, sys, time, base64
os.makedirs('/tmp/preview_out', exist_ok=True)
from agents import vnc_curate, vnc_sources
OV = json.load(open('run/overlays.json')).get('preview_layers', {})
import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
def fetch(vid):
    u = vnc_curate.hd_url(vid) or f"https://assets.mixkit.co/videos/{vid}/{vid}-360.mp4"
    p = f'/tmp/preview_out/ov_{vid}.mp4'; open(p, 'wb').write(vnc_curate.get(u, True, limit=60_000_000)); return p
class Ov:
    def __init__(s, vid, W=1080, H=1920):
        s.W, s.H = W, H
        e = {"source": "mixkit", "id": str(vid), "page": f"https://mixkit.co/free-stock-video/x-{vid}/"}
        s.path = fetch(vid)
        s.p = subprocess.Popen([FF, '-loglevel', 'error', '-stream_loop', '-1', '-i', s.path, '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    def next(s):
        b = s.p.stdout.read(s.W * s.H * 3)
        return np.frombuffer(b, np.uint8).reshape(s.H, s.W, 3).astype(np.float32) if len(b) == s.W * s.H * 3 else None
def screen(img, ov, op):
    if ov is None or op <= 0: return img
    return 255 - (255 - img) * (255 - ov * op) / 255
import numpy as np, cv2, subprocess
from PIL import Image, ImageDraw, ImageFont
W,H,FPS=1080,1920,30
base=cv2.cvtColor(cv2.imread('run/preview_base_E02.jpg'),cv2.COLOR_BGR2RGB).astype(np.float32)
# limpa legenda queimada (regiao y1130-1360) espelhando faixa acima + blur
y0,y1=1130,1360
patch=base[y0-(y1-y0):y0][::-1].copy()
base[y0:y1]=patch
base[y0-20:y1+20]=cv2.GaussianBlur(base[y0-20:y1+20],(0,0),6)
base=np.clip(base,0,255)
logo=Image.open('assets/vnc_logo.png').convert('RGBA')
a=np.array(logo).astype(np.float32)
lum=(a[...,0]*.299+a[...,1]*.587+a[...,2]*.114)
dark=(lum<70)&(a[...,3]>0)
a[dark,:3]=(236,232,250)
logo=Image.fromarray(a.astype(np.uint8))
bb=logo.getbbox(); logo=logo.crop(bb)
def sized(w):
    h=int(logo.height*w/logo.width); return logo.resize((w,h),Image.LANCZOS)
FONT='assets/fonts/AtkinsonHyperlegibleNext-Bold.ttf'
def text_layer(lines,size,color,ybot):
    im=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(im);f=ImageFont.truetype(FONT,size)
    y=H-ybot
    # bloco centrado; ybot = MarginV (borda inferior)
    hs=[d.textbbox((0,0),l,font=f)[3]+8 for l in lines]; y=ybot
    for l,h in zip(lines,hs):
        w=d.textlength(l,font=f); d.text(((W-w)/2,y),l,font=f,fill=color); y+=h
    return np.array(im).astype(np.float32)
cred=text_layer(['Habacuque 2:1-3'],30,(235,235,245,255),1095)
cta1=text_layer(['Curta, compartilhe','e inscreva-se no canal'],40,(255,255,255,255),1215)
cta2=text_layer(['E você, já se sentiu assim?','Conte nos comentários.'],34,(196,181,253,255),1350)

yy,xx=np.mgrid[0:H,0:W].astype(np.float32)
def ss(t,a,b):
    u=float(np.clip((t-a)/(b-a),0,1)); return u*u*(3-2*u)
def glow(cx,cy,r):
    d=np.sqrt((xx-cx)**2+((yy-cy)*1.1)**2); return np.clip(1-d/r,0,1)**2
SC=600/logo.width; LW,LH=600,int(logo.height*SC); LT=int(H*.39-LH/2); LX=(W-LW)//2
L=np.array(logo.resize((LW,LH),Image.LANCZOS)).astype(np.float32)
Lo=np.array(logo).astype(np.float32)
goldm=(Lo[...,0]>200)&(Lo[...,1]>130)&(Lo[...,2]<140)&(Lo[...,3]>40)
ry=np.arange(logo.height)[:,None]
sun=goldm&(ry<330); wordm=(ry>=700)
def part(mask):
    a=Lo.copy(); a[...,3]=a[...,3]*mask
    return np.array(Image.fromarray(a.astype(np.uint8)).resize((LW,LH),Image.LANCZOS)).astype(np.float32)
SUN=part(sun); WORD=part(wordm); BOOK=part((~sun)&(~wordm))
def blit(img,layer,dx=0,dy=0,alpha=None,clip_y=None):
    h,w=layer.shape[:2]; x=LX+dx; y=LT+dy
    la=layer[...,3:4]/255.0
    if alpha is not None: la=la*alpha
    y0=max(y,0); y1=min(y+h,H); sub=la[y0-y:y1-y]
    if clip_y is not None:
        rows=np.arange(y0,y1)[:,None,None]; sub=sub*(rows<clip_y)
    reg=img[y0:y1,x:x+w]; reg[:]=reg*(1-sub)+layer[y0-y:y1-y,:,:3]*sub
HOR=690
def txt(lines,size,color,top):
    im=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(im);f=ImageFont.truetype(FONT,size);y=top
    for l in lines:
        w=d.textlength(l,font=f);d.text(((W-w)/2,y),l,font=f,fill=color);y+=d.textbbox((0,0),l,font=f)[3]+8
    return np.array(im).astype(np.float32)
cred=txt(['Habacuque 2:1-3'],30,(235,235,245,255),1095)
cta1=txt(['Curta, compartilhe','e inscreva-se no canal'],40,(255,255,255,255),1215)
cta2=txt(['E você, já se sentiu assim?','Conte nos comentários.'],34,(196,181,253,255),1350)
def over(img,layer,al):
    la=layer[...,3:4]/255*al; return img*(1-la)+layer[...,:3]*la
a0,a1=80,340
top_row=base[a0].copy(); bot_row=base[a1].copy()
for yv in range(a0,a1):
    u=(yv-a0)/(a1-a0); base[yv]=top_row*(1-u)+bot_row*u
base[a0-10:a1+10]=cv2.GaussianBlur(base[a0-10:a1+10],(0,0),5)
blur=cv2.GaussianBlur(base,(0,0),9)
gold=np.array([255,190,80],np.float32)
vg=np.clip((yy-500)/900,0,1)[...,None]
top_logo=sized(210)
LEAD=1.0;T=9.5
_ctx={"get": vnc_curate.get, "cache": {}, "env": os.environ, "ua": vnc_curate.UA, "sleep": time.sleep, "budget": {}}
for _k,_v in OV.items():
    for _t in range(4):
        _ok,_ev,_hd=vnc_sources.rights({"source":"mixkit","id":str(_v),"page":f"https://mixkit.co/free-stock-video/x-{_v}/"},_ctx)
        if '429' not in _ev: break
        time.sleep(6*(_t+1))
    print('VNC_PREVIEW_RIGHTS',_k,_v,_ok,_ev)
    time.sleep(1.5)
OVS={k:Ov(v) for k,v in OV.items()}
OVT={'bokeh':0.3,'flare':1.6,'glitter':2.8}
SEEN={k:0 for k in OVS}
p=subprocess.Popen([FF,'-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-c:v','libx264','-preset','veryfast','-crf','30','-vf','scale=540:960','-pix_fmt','yuv420p','/tmp/preview_out/full.mp4'],stdin=subprocess.PIPE)
for i in range(int((LEAD+T)*FPS)):
    t=i/FPS-LEAD
    if t<0:
        img=base.copy(); tl=0.8
        arr=np.array(top_logo).astype(np.float32); h,w=arr.shape[:2]; la=arr[...,3:4]/255*tl
        img[105:105+h,(W-w)//2:(W-w)//2+w]=img[105:105+h,(W-w)//2:(W-w)//2+w]*(1-la)+arr[...,:3]*la
    else:
        k=ss(t,0.3,2.8)
        zf=1.0+0.045*(t/T)
        def push(a):
            h,w=a.shape[:2]; ch,cw=int(h/zf),int(w/zf); y0=int((h-ch)*0.45); x0=(w-cw)//2
            return cv2.resize(a[y0:y0+ch,x0:x0+cw],(w,h),interpolation=cv2.INTER_LINEAR)
        img=push(base)*(1-k)+push(blur)*k
        img=img*(1-0.45*k)+np.array([30,18,40],np.float32)*0.45*k   # a cena escurece, mas continua visivel
        img=img*(1-0.45*vg*ss(t,1.0,3.5))                              # base mais escura p/ legibilidade do texto
        for kk,(a,b,c,d,pk) in {'bokeh':(0.3,1.2,2.4,3.4,0.7),'flare':(1.6,2.4,2.8,3.8,0.85)}.items():
            if kk in OVS and a<=t<=d:
                fr=OVS[kk].next(); op=pk*min(ss(t,a,b),1-ss(t,c,d)); img=screen(img,fr,op)
        tl=0.8*(1-ss(t,0,0.9))
        if tl>0:
            arr=np.array(top_logo).astype(np.float32); h,w=arr.shape[:2]; la=arr[...,3:4]/255*tl
            img[105:105+h,(W-w)//2:(W-w)//2+w]=img[105:105+h,(W-w)//2:(W-w)//2+w]*(1-la)+arr[...,:3]*la
        # sol nasce atras do horizonte REAL da cena
        r=ss(t,0.8,2.8); sy=int(260*(1-r))
        sunc_y=LT+int(0.12*LH)+sy
        g=glow(W/2,min(sunc_y,HOR),700)[...,None]*(0.55*ss(t,0.8,3.0))
        img=img*(1-g)+gold*g
        blit(img,SUN,dy=sy,clip_y=HOR if r<1 else None)
        # livro se abre embaixo do sol
        b=ss(t,2.2,3.3)
        if b>0:
            sc=0.80+0.20*b; h=int(LH*sc); w=int(LW*sc)
            B2=cv2.resize(BOOK,(w,h),interpolation=cv2.INTER_AREA)
            cx=W//2; cy=LT+int(0.52*LH); la=B2[...,3:4]/255*b
            x=cx-w//2;y=cy-h//2
            img[y:y+h,x:x+w]=img[y:y+h,x:x+w]*(1-la)+B2[...,:3]*la
        # palavra escrita pela luz (varredura esq->dir com borda suave)
        wp=ss(t,2.8,3.9)
        if wp>0:
            edge=LX+wp*(LW+120)-60
            cols=np.arange(LW)+LX
            m=np.clip((edge-cols)/60,0,1)[None,:,None]
            lay=WORD.copy(); lay[...,3:4]=lay[...,3:4]*m
            blit(img,lay)
        # tracado do caminho dourado: linha que cresce do centro ate a referencia
        lp=ss(t,3.4,4.3)
        if lp>0:
            hw=int(200*lp); y0=1070
            la=np.zeros((H,W,1),np.float32); la[y0:y0+3,W//2-hw:W//2+hw]=1
            img=img*(1-la*0.9)+gold*la*0.9
        for layer,st in ((cred,3.4),(cta1,4.5),(cta2,6.0)):
            al=ss(t,st,st+0.8)
            if al>0: img=over(img,layer,al)
        if 'glitter' in OVS and t>=2.8:
            fr=OVS['glitter'].next(); img=screen(img,fr,0.55*ss(t,2.8,4.0))
        if 2.0<t<4.2:
            sa=np.sin(np.pi*(t-2.0)/2.2)**2*0.55
            sy0=min(sunc_y+int(0.07*LH),HOR-5) if r<1 else LT+int(0.2*LH)
            band=np.exp(-((yy-sy0)/5.0)**2)*np.exp(-np.abs(xx-W/2)/380)
            img=img+np.array([255,205,120],np.float32)*(band[...,None]*sa)
        vig=1-0.38*np.clip((np.sqrt(((xx-W/2)/W)**2+((yy-H*0.42)/H)**2)-0.28)/0.5,0,1)[...,None]
        img=img*vig
        gr=np.random.default_rng(i).normal(0,5.0,(H,W,1)).astype(np.float32)
        img=img+gr
        img=img*(1-ss(t,T-1.2,T))
    p.stdin.write(np.clip(img,0,255).astype(np.uint8).tobytes())
p.stdin.close();p.wait()

for q in OVS.values():
    q.p.kill()
subprocess.run([FF,'-y','-loglevel','error','-i','/tmp/preview_out/full.mp4','-c','copy','-movflags','+faststart','/tmp/preview_out/PREVIA_C3.mp4'])
import glob
for t in (1.6,2.6,3.4,4.4,5.4,9.0):
    subprocess.run([FF,'-y','-loglevel','error','-ss',str(t),'-i','/tmp/preview_out/PREVIA_C3.mp4','-frames:v','1','/tmp/preview_out/q_%s.png'%t])
from PIL import Image
fr=[Image.open('/tmp/preview_out/q_%s.png'%t) for t in (1.6,2.6,3.4,4.4,5.4,9.0)]
sh=Image.new('RGB',(270*6,480)); [sh.paste(f.resize((270,480)),(i*270,0)) for i,f in enumerate(fr)]; sh.save('/tmp/preview_out/strip.jpg',quality=80)
for nm in ('strip.jpg','PREVIA_C3.mp4'):
    b=base64.b64encode(open('/tmp/preview_out/'+nm,'rb').read()).decode()
    for i in range(0,len(b),3000): print('VNC_PREVIEW_B64',nm,i//3000,b[i:i+3000])
print('VNC_PREVIEW_OK', os.path.getsize('/tmp/preview_out/PREVIA_C3.mp4'))
