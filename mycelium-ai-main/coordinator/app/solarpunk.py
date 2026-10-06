"""Solar Punk City, fase 1: read-only top-down projectie van de wereld-store.

Alleen lezen via de coordinator-bridge (`InventoryReader.browse`,
type "locations"); nooit schrijven, geen posities bewaren, geen gates
omzeilen. Districten renderen uit live location-records; de layout is
een deterministische functie van de lijstvolgorde (geen sessie-state).

Fase 2+ voegt beweging/inputs toe; dit bestand blijft render-only.
"""

import json as _json

from .homebase import HOMEBASE_JS as _HOMEBASE_JS

MAP_W = 640
MAP_H = 400

# SP Home Base: ontwerp uit de referentiefoto (bakstenen pand met
# puntgevel, donkere kozijnen, rode dakpannen). Vaste landmark naast
# de spawn, herkenbaar in alle views. Enige game-eigendom: positie.
HOME_BASE = {
    "title": "SP Home Base",
    "blurb": ("Brick townhouse with a pointed gable, dark window "
              "frames and a red tile roof — the crew's front door "
              "in Solar Punk City."),
    "x": 620.0, "y": 250.0, "w": 240.0, "h": 170.0,
    "wall": "#8a4030", "frame": "#20261f", "roof": "#9c3a2b",
    "glass": "#e8d9a0",
}


def home_landmark() -> dict:
    """Vaste home-rect in wereldruimte, met herkomstvlag."""
    return {
        "x": HOME_BASE["x"], "y": HOME_BASE["y"],
        "w": HOME_BASE["w"], "h": HOME_BASE["h"],
        "title": HOME_BASE["title"], "home": True,
    }

# Zelfde wereldruimte als de bestaande play-sessies (play_workshop:
# PLAY_WORLD_W/H), zodat /solarpunk en /play één sessie delen.
WORLD_W = 3840.0
WORLD_H = 1400.0
WALL_H = 220.0
PLAYER_R = 30.0
# Solar-spawn: plein-voorland met vrij uitzicht op de
# NPC-werkspoten (JS spiegelt dit in SOLAR_SPAWN).
SPAWN = {"x": 1920.0, "y": 350.0, "a": 1.5708}


def district_rect(index: int, total: int) -> tuple:
    """Deterministische grid-layout: zelfde input -> zelfde rechthoek."""
    total = max(1, total)
    cols = max(1, round(total ** 0.5))
    rows = (total + cols - 1) // cols
    col = index % cols
    row = index // cols
    pad = 12
    cell_w = (MAP_W - pad * (cols + 1)) / cols
    cell_h = (MAP_H - pad * (rows + 1)) / rows
    return (
        pad + col * (cell_w + pad),
        pad + row * (cell_h + pad),
        cell_w,
        cell_h,
    )


def district_rect_world(index: int, total: int) -> tuple:
    """Zelfde grid als district_rect, geschaald naar wereldruimte."""
    x, y, w, h = district_rect(index, total)
    return (
        x * WORLD_W / MAP_W,
        y * WORLD_H / MAP_H,
        w * WORLD_W / MAP_W,
        h * WORLD_H / MAP_H,
    )


def world_payload(districts: list) -> list:
    """Districten -> bots- en tekenbare wereld-rects (wereldruimte)."""
    rects = []
    for pos, district in enumerate(districts or []):
        x, y, w, h = district_rect_world(pos, len(districts))
        rects.append({
            "x": round(x, 1), "y": round(y, 1),
            "w": round(w, 1), "h": round(h, 1),
            "title": str(district.get("title", "")),
        })
    return rects


SOLARPUNK_JS = """(function(){
"use strict";
var view=document.getElementById("spc-view"),map=document.getElementById("spc-map");
if(!view||!map||!view.getContext)return;
var ctx=view.getContext("2d"),mctx=map.getContext("2d");
var VW=view.width,VH=view.height,MW=map.width,MH=map.height;
var world=[];
try{world=JSON.parse(document.getElementById("spc-world").textContent||"[]");}catch(e){world=[];}
var WW=3840,WH=1400,WALL=220;
var SOLAR_SPAWN={x:1920,y:350,a:Math.PI/2};
var p={x:800,y:500,a:0};
var keys={};
var session=null,lastSync=0,dirty=false;
function postJSON(url,body){
  return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)}).then(function(r){return r.json();});
}
postJSON("/api/v1/play/session",{}).then(function(d){
  try{
    var stored=null;
    try{stored=window.localStorage.getItem("mycelium_play_session");}catch(e){}
    var resume=stored?postJSON("/api/v1/play/session",{session_id:stored}):null;
    var apply=function(s){
      if(s&&s.session_id){session=s.session_id;
        if(s.resumed){
          if(typeof s.x==="number")p.x=s.x;
          if(typeof s.y==="number")p.y=s.y;
          if(typeof s.a==="number")p.a=s.a;
          if(solidAt(p.x,p.y)){p.x=SOLAR_SPAWN.x;p.y=SOLAR_SPAWN.y;p.a=SOLAR_SPAWN.a;}
        }else{p.x=SOLAR_SPAWN.x;p.y=SOLAR_SPAWN.y;p.a=SOLAR_SPAWN.a;}
        try{window.localStorage.setItem("mycelium_play_session",session);}catch(e){}}
    };
    if(resume){resume.then(apply, function(){apply(d);});}else{apply(d);}
  }catch(e){if(d&&d.session_id)session=d.session_id;}
},function(){});
function solidAt(nx,ny){
  var r=30;
  if(nx<r||ny<r||nx>WW-r||ny>WH-r)return true;
  for(var i=0;i<world.length;i++){var o=world[i];
    if(nx+r>o.x&&nx-r<o.x+o.w&&ny+r>o.y&&ny-r<o.y+o.h)return true;}
  return false;
}
function cast(px,py,ang){
  var dx=Math.cos(ang),dy=Math.sin(ang),best=1e9,hit=null;
  for(var i=0;i<world.length;i++){var o=world[i];
    var t0=0,t1=1e9,ok=true;
    if(Math.abs(dx)<1e-9){if(px<o.x||px>o.x+o.w)ok=false;}
    else{var ta=(o.x-px)/dx,tb=(o.x+o.w-px)/dx;
      t0=Math.max(t0,Math.min(ta,tb));t1=Math.min(t1,Math.max(ta,tb));}
    if(ok){
      if(Math.abs(dy)<1e-9){if(py<o.y||py>o.y+o.h)ok=false;}
      else{var tc=(o.y-py)/dy,td=(o.y+o.h-py)/dy;
        t0=Math.max(t0,Math.min(tc,td));t1=Math.min(t1,Math.max(tc,td));}
    }
    if(ok&&t1>=Math.max(t0,0)&&t0<best){best=t0;hit=o;}
  }
  var edge=1e9;
  if(dx>1e-9)edge=Math.min(edge,(WW-px)/dx);else if(dx<-1e-9)edge=Math.min(edge,(0-px)/dx);
  if(dy>1e-9)edge=Math.min(edge,(WH-py)/dy);else if(dy<-1e-9)edge=Math.min(edge,(0-py)/dy);
  if(edge<best){best=edge;hit=null;}
  return {d:best,hit:hit,hx:px+dx*best,hy:py+dy*best};
}
window.addEventListener("keydown",function(e){
  var a=document.activeElement;
  if(a&&("INPUT,SELECT,TEXTAREA".indexOf(a.tagName)>=0))return;
  var k=(e.key||"").toLowerCase();
  if(["arrowup","arrowdown","arrowleft","arrowright"," "].indexOf(k)>=0)e.preventDefault();
  keys[k]=true;
});
window.addEventListener("keyup",function(e){keys[(e.key||"").toLowerCase()]=false;});
window.addEventListener("blur",function(){keys={};});
var drag=null;
try{view.style.touchAction="none";}catch(_){}
view.addEventListener("pointerdown",function(e){drag={x:e.clientX};try{view.setPointerCapture(e.pointerId);}catch(_){}});
view.addEventListener("pointermove",function(e){if(!drag)return;var dx=e.clientX-drag.x;drag.x=e.clientX;if(dx){p.a+=dx*0.0055;dirty=true;}});
function endDrag(){drag=null;}
view.addEventListener("pointerup",endDrag);
view.addEventListener("pointercancel",endDrag);
var last=0;
function frame(t){
  if(document.hidden){requestAnimationFrame(frame);return;}
  var dt=Math.min(0.05,(t-last)/1000||0.016);last=t;
  var turn=2.4*dt,sp=300*dt,moved=false;
  if(keys["arrowleft"]){p.a-=turn;moved=true;}
  if(keys["arrowright"]){p.a+=turn;moved=true;}
  var fx=0,fy=0;
  if(keys["w"]||keys["arrowup"]){fx+=1;moved=true;}
  if(keys["s"]||keys["arrowdown"]){fx-=1;moved=true;}
  if(keys["a"]){fy-=1;moved=true;}
  if(keys["d"]){fy+=1;moved=true;}
  if(fx||fy){
    var ca=Math.cos(p.a),sa=Math.sin(p.a);
    var nx=p.x+(fx*ca-fy*sa)*sp,ny=p.y+(fx*sa+fy*ca)*sp;
    if(!solidAt(nx,p.y)){p.x=nx;} 
    if(!solidAt(p.x,ny)){p.y=ny;}
  }
  dirty=dirty||moved;
  var FOV=66*Math.PI/180,N=120;
  var sky=ctx.createLinearGradient(0,0,0,VH/2);
  sky.addColorStop(0,"#a8d0e0");sky.addColorStop(0.7,"#ffe9b8");sky.addColorStop(1,"#f2e2ac");
  ctx.fillStyle=sky;ctx.fillRect(0,0,VW,VH/2+1);
  ctx.fillStyle="rgba(255,255,255,0.55)";
  var tsec=(t/1000)||0;
  for(var ci=0;ci<3;ci++){
    var ccx=((tsec*(6+ci*3)+ci*430)%(VW+360))-180;
    var ccy=VH*(0.10+ci*0.07);
    ctx.beginPath();ctx.ellipse(ccx,ccy,70,14,0,0,7);ctx.fill();
    ctx.beginPath();ctx.ellipse(ccx+40,ccy+6,50,11,0,0,7);ctx.fill();
  }
  var sunRel=0.9-p.a;
  while(sunRel>Math.PI)sunRel-=2*Math.PI;
  while(sunRel<-Math.PI)sunRel+=2*Math.PI;
  if(Math.abs(sunRel)<FOV/2){
    var sunX=VW/2+Math.tan(sunRel)*(VW/2)/Math.tan(FOV/2);
    ctx.fillStyle="rgba(255,244,214,0.28)";
    ctx.beginPath();ctx.arc(sunX,VH*0.18,36,0,7);ctx.fill();
    ctx.fillStyle="rgba(255,246,220,0.95)";
    ctx.beginPath();ctx.arc(sunX,VH*0.18,22,0,7);ctx.fill();
  }
  var gr=ctx.createLinearGradient(0,VH/2,0,VH);
  gr.addColorStop(0,"#4c8a52");gr.addColorStop(1,"#2c5a32");
  ctx.fillStyle=gr;ctx.fillRect(0,VH/2,VW,VH/2);
  ctx.fillStyle="rgba(240,238,220,0.35)";
  ctx.fillRect(0,VH/2,VW,2);
  for(var i=0;i<N;i++){
    var ang=p.a-FOV/2+FOV*i/(N-1);
    var r=cast(p.x,p.y,ang);
    var dist=Math.max(1,r.d*Math.cos(ang-p.a));
    var h=Math.min(VH*3,(WALL/dist)*900);
    var shade=Math.max(0.25,Math.min(1,900/(dist+300)));
    var wpx=VW/N+1,wx=i*VW/N,wy=(VH-h)/2;
    if(r.hit&&r.hit.home){
      var o=r.hit,u=0.5;
      if(Math.abs(r.hx-o.x)<1||Math.abs(r.hx-(o.x+o.w))<1){u=(r.hy-o.y)/o.h;}
      else{u=(r.hx-o.x)/o.w;}
      u=Math.max(0,Math.min(1,u));
      ctx.fillStyle="rgba("+(150*shade+30|0)+","+(62*shade+12|0)+","+(44*shade+8|0)+",1)";
      ctx.fillRect(wx,wy,wpx,h);
      ctx.fillStyle="rgba("+(120*shade+24|0)+","+(50*shade+10|0)+","+(36*shade+7|0)+",1)";
      ctx.fillRect(wx,wy,wpx,Math.max(1,h*0.05));
      if(dist<900){
      if(u>0.44&&u<0.56){
        ctx.fillStyle="rgba("+(30*shade+8|0)+","+(22*shade+8|0)+","+(20*shade+6|0)+",1)";
        ctx.fillRect(wx,wy+h*0.35,wpx,h*0.65);
        ctx.fillStyle="rgba(232,217,160,"+(0.9*shade+0.1).toFixed(2)+")";
        ctx.fillRect(wx,wy+h*0.42,wpx,h*0.06);
      }else if((u>0.14&&u<0.30)||(u>0.70&&u<0.86)){
        ctx.fillStyle="rgba(232,217,160,"+(0.85*shade+0.1).toFixed(2)+")";
        ctx.fillRect(wx,wy+h*0.30,wpx,h*0.28);
        ctx.fillStyle="rgba("+(32*shade+8|0)+","+(38*shade+8|0)+","+(31*shade+6|0)+",1)";
        ctx.fillRect(wx,wy+h*0.42,wpx,Math.max(1,h*0.03));
      }
      }
    }else{
      var g=r.hit?90:60;
      ctx.fillStyle="rgba("+(60*shade|0)+","+(g+80*shade|0)+","+(60*shade|0)+",1)";
      ctx.fillRect(wx,wy,wpx,h);
      if(r.hit&&dist<900){
        var o2=r.hit,u2=0.5;
        if(Math.abs(r.hx-o2.x)<1||Math.abs(r.hx-(o2.x+o2.w))<1){u2=(r.hy-o2.y)/o2.h;}
        else{u2=(r.hx-o2.x)/o2.w;}
        u2=Math.max(0,Math.min(1,u2));
        if(((u2*20)|0)%2===0){
          ctx.fillStyle="rgba("+(40*shade|0)+","+(g+60*shade|0)+","+(40*shade|0)+",1)";
          ctx.fillRect(wx,wy,wpx,Math.max(1,h*0.22));
        }
      }
    }
  }
  window.spcPosX=p.x;window.spcPosY=p.y;
  if(window.spcDrawActors)window.spcDrawActors(p);
  mctx.fillStyle="#10240f";mctx.fillRect(0,0,MW,MH);
  var sx=MW/WW,sy=MH/WH;
  for(var j=0;j<world.length;j++){var o=world[j];
    mctx.fillStyle=o.home?"#8a4030":"#4caf6d";
    mctx.fillRect(o.x*sx,o.y*sy,Math.max(2,o.w*sx),Math.max(2,o.h*sy));
    if(o.home){mctx.strokeStyle="#9c3a2b";mctx.beginPath();
      mctx.moveTo(o.x*sx,(o.y+o.h)*sy);
      mctx.lineTo((o.x+o.w/2)*sx,o.y*sy-4);
      mctx.lineTo((o.x+o.w)*sx,(o.y+o.h)*sy);mctx.stroke();}}
  mctx.strokeStyle="#ffe9b8";mctx.beginPath();
  mctx.moveTo(p.x*sx,p.y*sy);
  mctx.lineTo((p.x+Math.cos(p.a)*220)*sx,(p.y+Math.sin(p.a)*220)*sy);mctx.stroke();
  mctx.fillStyle="#ffefc2";mctx.beginPath();
  mctx.arc(p.x*sx,p.y*sy,3,0,7);mctx.fill();
  (function(){
    var _actors=window.__spcActors||[];
    for(var k=0;k<_actors.length;k++){
      var a=_actors[k];
      mctx.fillStyle=a.color||"#a5c48a";
      mctx.beginPath();
      mctx.arc(a.x*sx,a.y*sy,2.5,0,7);mctx.fill();
    }
  })();
  var now=Date.now();
  if(session&&dirty&&now-lastSync>2500){
    lastSync=now;dirty=false;
    postJSON("/api/v1/play/position",{session_id:session,
      x:Math.round(p.x),y:Math.round(p.y),a:+p.a.toFixed(3),
      zone:"solarpunk"}).catch(function(){});
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
})();"""


SCAN_JS = """(function(){
"use strict";
var box=document.getElementById("spc-scan");
if(!box)return;
function el(id){return document.getElementById(id);}
function say(t){box.innerHTML='<p class="muted">'+t+'</p>';}
function postJSON(url,body){
  return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)}).then(function(r){
    return r.json().then(function(j){return {ok:r.ok,st:r.status,body:j};});});
}
var device=null,timer=null,frames=0,errors=0;
function showShot(id){
  var shot=el("spc-scan-shot");
  if(!shot||!id)return;
  shot.innerHTML='<img src="/api/v1/cameras/observations/'+encodeURIComponent(id)+'/image" style="max-width:100%;border-radius:6px" alt="Camera frame">';
}
function refresh(){
  fetch("/api/v1/cameras").then(function(r){return r.json();}).then(function(list){
    var found=null;
    for(var i=0;i<list.length;i++){
      if(list[i].source==="insta360"&&(list[i].kinds||[]).indexOf("snapshot")>=0){found=list[i];break;}
    }
    device=found;
    if(!device){
      say("No Insta360 registered. Plug the X3 in webcam mode, then register it.");
      el("spc-scan-reg").hidden=false;el("spc-scan-go").hidden=true;el("spc-scan-snap").hidden=true;el("spc-scan-stop").hidden=true;
      return;
    }
    el("spc-scan-reg").hidden=true;
    fetch("/api/v1/cameras/"+encodeURIComponent(device.device_id)+"/observations").then(function(r){
      return r.json();}).then(function(obs){
      say("Camera <b>"+device.device_id+"</b> ready · "+obs.length+" stored frames. Rotate the camera slowly, then Start scan (one frame every ~10s, max 30).");
      el("spc-scan-go").hidden=false;el("spc-scan-snap").hidden=false;
    },function(){say("Camera <b>"+device.device_id+"</b> ready.");el("spc-scan-go").hidden=false;el("spc-scan-snap").hidden=false;});
  },function(){say("Camera list unreachable.");});
}
el("spc-scan-find").onclick=refresh;
el("spc-scan-reg").onclick=function(){
  postJSON("/api/v1/cameras/register",{name:"Insta360 X3",kinds:["snapshot"],source:"insta360"}).then(function(r){
    say(r.ok?"Registered.":"Register refused: "+JSON.stringify(r.body).slice(0,120));refresh();
  },function(){say("Register failed.");});
};
el("spc-scan-go").onclick=function(){
  if(!device||timer)return;
  frames=0;errors=0;
  el("spc-scan-go").hidden=true;el("spc-scan-snap").hidden=true;el("spc-scan-stop").hidden=false;
  say("Scanning… 0 frames. Rotate slowly.");
  timer=setInterval(function(){
    postJSON("/api/v1/cameras/"+encodeURIComponent(device.device_id)+"/probe-grab",{timeout:8}).then(function(r){
      if(r.ok){frames++;errors=0;
        var id=(r.body.camera_observation&&r.body.camera_observation.observation_id)||"?";
        showShot(id);
        say("Scanning… "+frames+" frames · last "+id+".");
        if(frames>=30)stop("Done — 30 frames stored as observations.");
      }else{errors++;
        say("Grab refused ("+r.st+"). "+errors+"/3 errors.");
        if(errors>=3)stop("Stopped after 3 errors: "+JSON.stringify(r.body).slice(0,140));
      }
    },function(){errors++;if(errors>=3)stop("Stopped: backend unreachable.");});
  },10000);
  function stop(msg){if(timer){clearInterval(timer);timer=null;}
    el("spc-scan-go").hidden=false;el("spc-scan-snap").hidden=false;el("spc-scan-stop").hidden=true;say(msg);}
  el("spc-scan-stop").onclick=function(){stop("Stopped by you — "+frames+" frames kept.");};
};
el("spc-scan-snap").onclick=function(){
  if(!device||timer)return;
  say("Beeld ophalen…");
  postJSON("/api/v1/cameras/"+encodeURIComponent(device.device_id)+"/probe-grab",{timeout:8}).then(function(r){
    if(r.ok){var id=(r.body.camera_observation&&r.body.camera_observation.observation_id)||"";
      showShot(id);say("Beeld van "+device.device_id+" ("+id+").");
    }else{say("Grab refused ("+r.st+"). "+JSON.stringify(r.body).slice(0,140));}
  },function(){say("Grab failed: backend unreachable.");});
};
refresh();
})();"""


TOWN_JS = """(function(){
"use strict";
var box=document.getElementById("spc-town");
if(!box)return;
var input=document.getElementById("spc-town-input");
var convo=null;
try{convo=window.localStorage.getItem("mycelium_town_convo");}catch(e){}
function esc(t){return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;");}
function show(list){
  if(!list.length){box.innerHTML='<p class="muted">Quiet square. Say hi.</p>';return;}
  box.innerHTML=list.slice(-12).map(function(m){
    return '<p><b>'+esc(m.role)+'</b> '+esc(m.content)+'</p>';
  }).join("");
}
function load(){
  if(!convo)return;
  fetch("/api/v1/town/conversations/"+encodeURIComponent(convo)+"/messages").then(function(r){
    return r.json();}).then(show,function(){});
}
function ensure(fn){
  if(convo){fn();return;}
  fetch("/api/v1/town/conversations",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({title:"Town square",participants:["you"]})}).then(function(r){
    return r.json();}).then(function(d){
    convo=d.conversation_id;
    try{window.localStorage.setItem("mycelium_town_convo",convo);}catch(e){}
    fn();
  },function(){});
}
document.getElementById("spc-town-send").onclick=function(){
  var text=input.value||"";
  if(!text.trim())return;
  input.value="";
  window.spcSay(text);
};
window.spcSay=function(text,after){
  ensure(function(){
    fetch("/api/v1/town/conversations/"+encodeURIComponent(convo)+"/messages",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({speaker:"you",role:"human",text:text,npc_id:(window.spcTargetNpc||"")})}).then(function(r){
      return r.json();}).then(function(d){load();if(after)after(d);},function(){if(after)after(null);});
  });
};
function spcSetTarget(npc){
  window.spcTargetNpc=npc||"";
  if(npc){input.placeholder="Tegen "+String(npc)+" zeggen…";}
  else{input.placeholder="Say something…";}
}
window.spcSetTarget=spcSetTarget;
var hudSend=document.getElementById("spc-hud-send");
var hudInput=document.getElementById("spc-hud-input");
var hudReply=document.getElementById("spc-hud-reply");
if(hudSend&&hudInput){
  var hudGo=function(){
    var text=hudInput.value||"";
    if(!text.trim())return;
    hudInput.value="";
    if(hudReply)hudReply.innerHTML='<p class="muted">… (bewoner denkt na, kan ~30s duren)</p>';
    window.spcSay(text,function(d){
      if(!hudReply)return;
      var turn=d&&d.npc_turn;
      if(turn&&turn.content){
        hudReply.innerHTML='<p><b>'+esc(turn.role||"npc")+'</b> '+esc(turn.content)+'</p>';
      }else{hudReply.innerHTML='<p class="muted">Verstuurd — antwoord staat op het plein.</p>';}
    });
  };
  hudSend.onclick=hudGo;
  hudInput.addEventListener("keydown",function(e){
    if((e.key||"")==="Enter"){e.preventDefault();hudGo();}
  });
}
load();
})();"""


ACTORS_JS = """(function(){
"use strict";
var view=document.getElementById("spc-view"),map=document.getElementById("spc-map");
if(!view||!map)return;
var ctx=view.getContext("2d"),mctx=map.getContext("2d");
var actors=[];
window.__spcActors=[];
try{actors=JSON.parse(document.getElementById("spc-actors").textContent||"[]");}catch(e){actors=[];}
var COLORS=["#a5c48a","#d9a441","#7fb8d9","#c9a0dc","#e08e8e","#8fd9c9"];
var feed=document.getElementById("spc-actors-feed");
var bar=document.getElementById("spc-near");
function esc(t){return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;");}
function colorOf(id){
  var order=["mos","oracle","smid","archivaris","voorman","seinwachter"];
  var i=order.indexOf(id);return COLORS[i<0?0:i];
}
function load(){
  fetch("/api/v1/town/actors").then(function(r){return r.json();}).then(function(d){
    actors=(d.actors||[]).map(function(a){
      var names={mos:"Mos",oracle:"Orakel",smid:"Smid",archivaris:"Archivaris",voorman:"Voorman",seinwachter:"Seinwachter"};
      a.name=names[a.npc_id]||a.npc_id;return a;});
    window.__spcActors=actors.map(function(a){
      return {x:a.x,y:a.y,color:colorOf(a.npc_id)};});
    if(feed){
      var items=(d.activity||[]).slice(0,8);
      feed.innerHTML=items.length?items.map(function(it){
        return '<p><b>'+esc(it.npc_id)+'</b> <span class="muted">'+esc(it.kind)+'</span> '+esc(it.detail)+'</p>';
      }).join(""):'<p class="muted">No activity yet.</p>';
    }
  },function(){});
}
function drawActors(p,VW,VH){
  var FOV=66*Math.PI/180;
  var seen=[];
  for(var i=0;i<actors.length;i++){var a=actors[i];
    var dx=a.x-p.x,dy=a.y-p.y;
    var dist=Math.sqrt(dx*dx+dy*dy);
    if(dist<40||dist>1600)continue;
    var rel=Math.atan2(dy,dx)-p.a;
    while(rel>Math.PI)rel-=2*Math.PI;
    while(rel<-Math.PI)rel+=2*Math.PI;
    if(Math.abs(rel)>FOV/2+0.35)continue;
    seen.push({a:a,dist:dist,rel:rel});
  }
  seen.sort(function(u,v){return v.dist-u.dist;});
  for(var j=0;j<seen.length;j++){var s=seen[j];
    var sx=VW/2+Math.tan(s.rel)*(VW/2)/Math.tan(FOV/2);
    var h=Math.min(VH*0.95,(110/s.dist)*900);
    var w=Math.max(3,h*0.34);
    var base=VH*0.82;
    var shade=Math.max(0.3,Math.min(1,420/(s.dist+120)));
    var c=colorOf(s.a.npc_id);
    ctx.globalAlpha=shade;
    ctx.fillStyle=c;
    ctx.beginPath();
    ctx.ellipse(sx,base,w*0.9,Math.max(2,h*0.05),0,0,7);
    ctx.fill();
    ctx.fillRect(sx-w/2,base-h*0.62,w,h*0.58);
    ctx.beginPath();
    ctx.arc(sx,base-h*0.74,w*0.42,0,7);
    ctx.fill();
    ctx.globalAlpha=1;
    s._sx=sx;s._h=h;
  }
  ctx.font="11px Segoe UI,system-ui,sans-serif";
  var taken=[];
  for(var q=seen.length-1;q>=0;q--){var t=seen[q],sx2=t._sx;
    var label=t.a.name+" · "+(t.a.status||"idle");
    var lw=ctx.measureText(label).width+12;
    var lx=sx2-lw/2,overlap=false;
    for(var z=0;z<taken.length;z++){
      if(lx<taken[z][1]&&lx+lw>taken[z][0]){overlap=true;break;}
    }
    if(overlap)continue;
    taken.push([lx,lx+lw]);
    var ly=Math.min(Math.max(16,base-t._h-26),VH-40);
    ctx.fillStyle="rgba(20,26,20,0.85)";
    ctx.fillRect(lx,ly,lw,16);
    ctx.fillStyle="#ece7d8";
    ctx.fillText(label,lx+6,ly+12);
    if(t.a.detail){
      var d=t.a.detail.length>28?t.a.detail.slice(0,27)+"…":t.a.detail;
      var dw=ctx.measureText(d).width+10;
      var dy2=Math.min(Math.max(34,base-t._h-44),VH-58);
      ctx.fillStyle="rgba(20,26,20,0.7)";
      ctx.fillRect(sx2-dw/2,dy2-15,dw,15);
      ctx.fillStyle="#d9a441";
      ctx.fillText(d,sx2-dw/2+5,dy2-4);
    }
  }
  var near=null;
  for(var k=0;k<actors.length;k++){var b=actors[k];
    var ndx=b.x-p.x,ndy=b.y-p.y;
    var nd=ndx*ndx+ndy*ndy;
    if(nd<100*100&&(!near||nd<near.d)){near={a:b,d:nd};}
  }
  if(bar){
    if(near){
      var html="Dicht bij <b>"+esc(near.a.name)+"</b> ("+esc(near.a.status||"idle")+") — <button type='button' id='spc-near-talk'>Praat</button> <button type='button' id='spc-near-del'>Delegeer</button>";
      if(html===window.__spcHudHtml)return;
      window.__spcHudHtml=html;
      bar.hidden=false;
      bar.innerHTML=html;
      var hud=document.getElementById("spc-hud");
      if(hud)hud.innerHTML=html.replace(/spc-near-/g,"spc-hud-");
      var nid=near.a.npc_id;
      var wire=function(id,fn){var b=document.getElementById(id);if(b)b.onclick=fn;};
      var talkFn=function(){
        if(window.spcSetTarget)window.spcSetTarget(nid);
        var chat=document.getElementById("spc-hud-chat");
        if(chat)chat.hidden=false;
        var inp=document.getElementById("spc-hud-input");
        if(inp)inp.focus();
      };
      var delFn=function(){
        window.spcDelegateNpc=nid;
        var b=document.getElementById("spc-bureau");
        if(b)b.scrollIntoView();
      };
      wire("spc-near-talk",talkFn);wire("spc-hud-talk",talkFn);
      wire("spc-near-del",delFn);wire("spc-hud-del",delFn);
    }else{
      window.__spcHudHtml="";
      if(!bar.hidden)bar.hidden=true;
      var hud2=document.getElementById("spc-hud");
      var idle='<p class="muted">Loop naar een bewoner om te praten.</p>';
      if(hud2&&hud2.innerHTML!==idle)hud2.innerHTML=idle;
      if(window.spcTargetNpc&&window.spcSetTarget)window.spcSetTarget("");
    }
  }
}
var mlast=0;
setInterval(function(){
  load();
  var now=Date.now();
  if(now-mlast<4000)return;mlast=now;
  try{
    var VW=view.width,VH=view.height;
    drawActors({x:window.spcPosX||800,y:window.spcPosY||500},VW,VH);
  }catch(e){}
},1000);
load();
window.spcDrawActors=function(p){try{drawActors(p,view.width,view.height);}catch(e){}};
})();"""


BUREAU_JS = """(function(){
"use strict";
var box=document.getElementById("spc-bureau");
if(!box)return;
var dial=document.getElementById("spc-autonomy");
var formNpc=document.getElementById("spc-del-npc");
var formReq=document.getElementById("spc-del-req");
var note=document.getElementById("spc-del-note");
function esc(t){return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;");}
function postJSON(url,body){
  return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)}).then(function(r){
    return r.json().then(function(j){return {ok:r.ok,st:r.status,body:j};});});
}
function chip(status){
  if(status==="proposed")return '<span class="muted">wacht op YES</span>';
  if(status==="approved"||status==="auto-queued")return 'gequeued';
  return esc(status);
}
function card(p){
  var h='<div class="proposal"><p><b>'+esc(p.kind)+'</b> — '+esc(p.goal)+
    ' <span class="muted">('+esc(p.npc_id)+' · '+chip(p.status)+')</span></p>'+
    '<p class="muted">Waarom: '+esc(p.justification)+'</p>'+
    '<p class="muted">Raakt: '+esc(p.blast_radius)+
    ' · zekerheid '+esc(String(p.confidence))+'</p>';
  if(p.status==="proposed"){
    h+='<p><button type="button" data-yes="'+esc(p.proposal_id)+'">YES</button> '+
      '<button type="button" data-no="'+esc(p.proposal_id)+'">Afwijzen</button></p>';
  }else if(p.queue_task_id){
    h+='<p class="muted">taak #'+esc(String(p.queue_task_id))+
      ' · beslist door '+esc(p.decided_by||"?")+'</p>';
  }else{
    h+='<p class="muted">beslist door '+esc(p.decided_by||"?")+'</p>';
  }
  return h+'</div>';
}
function load(){
  fetch("/api/v1/town/autonomy").then(function(r){return r.json();}).then(function(d){
    if(!dial)return;
    var rules=d.rules||{};
    var names=Object.keys(rules);
    var txt=names.length?names.map(function(n){
      return n+" → "+rules[n].join(", ");}).join(" · "):
      "niemand mag iets autonoom (default)";
    dial.innerHTML='<p class="muted">Dial: '+esc(txt)+
      ' · nooit: hardware, desktop-invoer, fabricage.</p>';
  },function(){});
  fetch("/api/v1/town/proposals").then(function(r){return r.json();}).then(function(d){
    var list=d.proposals||[];
    box.innerHTML=list.length?list.slice(0,10).map(card).join(""):
      '<p class="muted">Geen voorstellen. Delegeer hierboven.</p>';
    var btns=box.querySelectorAll("button[data-yes],button[data-no]");
    for(var i=0;i<btns.length;i++){btns[i].onclick=function(){
      var id=this.getAttribute("data-yes")||this.getAttribute("data-no");
      var dec=this.hasAttribute("data-yes")?"YES":"nee";
      var b=this;b.disabled=true;
      postJSON("/api/v1/town/proposals/"+encodeURIComponent(id)+"/decide",
        {decision:dec,decided_by:"you"}).then(function(){load();},function(){load();});
    };}
  },function(){});
}
var go=document.getElementById("spc-del-go");
if(go)go.onclick=function(){
  var npc=formNpc?formNpc.value:"voorman";
  var req=formReq?formReq.value:"";
  if(!req.trim()){if(note)note.textContent="Schrijf eerst het verzoek.";return;}
  if(note)note.textContent="NPC denkt na…";
  postJSON("/api/v1/town/npc/"+encodeURIComponent(npc)+"/delegate",
    {request:req}).then(function(r){
    if(r.ok){if(note)note.textContent="Voorstel bewaard — beslis hieronder.";
      if(formReq)formReq.value="";}
    else{if(note)note.textContent="Geweigerd ("+r.st+"): "+
      JSON.stringify(r.body).slice(0,160);}
    load();
  },function(){if(note)note.textContent="Backend onbereikbaar.";});
};
setInterval(function(){
  if(window.spcDelegateNpc&&formNpc){formNpc.value=window.spcDelegateNpc;
    window.spcDelegateNpc="";}
  load();
},6000);
load();
})();"""


def district_payload(results) -> list:
    """SearchResult-lijst -> kale dicts voor render(). Negeert alles
    behalve id/titel/snippet; provenance tonen we als badge-tekst."""
    districts = []
    for item in results or []:
        districts.append({
            "entity_id": str(getattr(item, "entity_id", "")),
            "title": str(getattr(item, "title", "") or "Unnamed district"),
            "snippet": str(getattr(item, "snippet", "") or ""),
        })
    return districts


def _residents_panel() -> str:
    """Bewonerslijst met eerlijke waak-status. Import faalt nooit hard."""
    import os as _os
    from . import ui as _ui
    try:
        from .hermes_npc import HERMES_NPCS as _npcs
    except Exception:
        return ("<p class=\"muted\">Bewonerslijst tijdelijk "
                "onbeschikbaar.</p>")
    awake = bool((_os.environ.get("HERMES_API_KEY") or "").strip())
    chip = ("🟢 wakker" if awake
            else "😴 slaapt (geen model — zie keys-uitleg hieronder)")
    rows = "".join(
        f"<li><b>{_ui.esc(npc.get('name', key))}</b> — "
        f"{_ui.esc(npc.get('role', ''))} "
        f"<span class=\"muted\">{chip}</span></li>"
        for key, npc in _npcs.items())
    return f"<ul>{rows}</ul>"


def render(districts: list, error: str = "") -> str:
    """Volledige HTML-pagina. Nooit exceptions: bij lege input een
    eerlijk paneel, nooit een traceback."""
    from . import ui as _ui

    districts = districts or []
    total = len(districts)
    world = world_payload(districts) + [home_landmark()]
    # SVG kaart in map-space (640x400); 3D/minimap/JSON in wereldruimte.
    sights = []
    for pos, district in enumerate(districts):
        x, y, w, h = district_rect(pos, total)
        sights.append({"x": x, "y": y, "w": w, "h": h,
                       "title": district.get("title", ""),
                       "ref": district.get("entity_id", ""),
                       "home": False})
    home = home_landmark()
    sights.append({"x": home["x"] * MAP_W / WORLD_W,
                   "y": home["y"] * MAP_H / WORLD_H,
                   "w": home["w"] * MAP_W / WORLD_W,
                   "h": home["h"] * MAP_H / WORLD_H,
                   "title": home["title"], "ref": "home", "home": True})
    rects = []
    rows = []
    for block in sights:
        x, y, w, h = (block["x"], block["y"], block["w"], block["h"])
        title = _ui.esc(block.get("title", ""))
        ref = _ui.esc(block.get("ref", ""))
        if block.get("home"):
            fill = f' fill="{HOME_BASE["wall"]}"'
        else:
            fill = ""
        rects.append(
            f'<g><rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" class="district" rx="10"{fill}>'
            f'<title>{title} ({ref})</title></rect>'
            f'<text x="{x + 10:.1f}" y="{y + 24:.1f}" '
            f'class="district-label">{title}</text></g>'
        )
        if not block.get("home"):
            rows.append(
                f"<li><b>{title}</b> "
                f"<span class=\"muted\">{ref}</span></li>")
    rows.append(
        f"<li><b>⌂ {_ui.esc(HOME_BASE['title'])}</b> "
        f"<span class=\"muted\">home landmark</span></li>")
    if rects:
        svg_map = (
            f'<svg viewBox="0 0 {MAP_W} {MAP_H}" role="img" '
            'aria-label="Solar Punk City districts" class="city-map">'
            + "".join(rects) + "</svg>"
        )
        district_list = "<ul>" + "".join(rows) + "</ul>"
    else:
        svg_map = (
            '<div class="panel"><h2>Quiet city</h2>'
            "<p class=\"muted\">No districts in the world store yet — "
            "add locations in INVENTory and they appear here. "
            "Nothing is stored here; this page only reads.</p></div>"
        )
        district_list = ""
    notice = ""
    if error:
        notice = (
            '<div class="panel"><h2>World store offline</h2>'
            f"<p class=\"muted\">{_ui.esc(error)} — showing an empty "
            "city rather than guessing. Start INVENTory on "
            ":8080 and reload.</p></div>"
        )
    residents = _residents_panel()
    actors = []
    try:
        from .town_actors import list_actors as _list_actors
        actors = _list_actors()
    except Exception:
        actors = []
    actors_json = _json.dumps(actors).replace("</", "<\\/")
    world_json = _json.dumps(
        world_payload(districts) + [home_landmark()]).replace(
        "</", "<\\/")
    main = f"""<h1>☀️ Solar Punk City</h1>
    <p class="muted">A living city for agents — walk it in first person.
    Districts are INVENTory locations. Your position saves to your
    play session (same session as /play); movement never touches
    entities or gates.</p>
    <p class="muted">{total} districts · WASD lopen · pijltjes of slepen kijken ·
    positie + kijkrichting bewaart elke ~2,5s</p>
    {notice}
    <div class="panel"><h2>⌂ {_ui.esc(HOME_BASE['title'])}</h2>
    <p class="muted">{_ui.esc(HOME_BASE['blurb'])}</p>
    <div id="hb-3d" style="width:100%;max-width:960px;height:450px"></div>
    <p class="muted">Sleep om rond te kijken · scroll om te zoomen ·
    <a href="/homebase">Full view →</a></p></div>
    <div class="panel"><h2>First person</h2>
    <canvas id="spc-view" width="640" height="360"></canvas>
    <div id="spc-hud"><p class="muted">Loop naar een bewoner om te praten.</p></div>
    <div id="spc-hud-chat" hidden>
    <input id="spc-hud-input" type="text" placeholder="Zeg iets tegen de bewoner…" aria-label="Praat met bewoner" autocomplete="off">
    <button id="spc-hud-send" type="button">Zeg</button></div>
    <div id="spc-hud-reply" aria-live="polite"></div></div>
    <div class="panel"><h2>Bird's eye</h2>
    <canvas id="spc-map" width="320" height="200"></canvas></div>
    <div class="panel"><h2>Room scan</h2>
    <div id="spc-scan"><p class="muted">Looking for camera…</p></div>
    <div id="spc-scan-shot"></div>
    <button id="spc-scan-find" type="button">Find camera</button>
    <button id="spc-scan-reg" type="button" hidden>Register Insta360</button>
    <button id="spc-scan-go" type="button" hidden>Start scan</button>
    <button id="spc-scan-snap" type="button" hidden>Bekijk beeld (1 klik)</button>
    <button id="spc-scan-stop" type="button" hidden>Stop</button></div>
    <div class="panel"><h2>Residents</h2>
    {residents}</div>
    <div class="panel"><h2>Town square</h2>
    <div id="spc-near" hidden></div>
    <div id="spc-town"><p class="muted">Quiet square.</p></div>
    <input id="spc-town-input" type="text" placeholder="Say something…" aria-label="Town message" autocomplete="off">
    <button id="spc-town-send" type="button">Say</button></div>
    <div class="panel"><h2>What they do</h2>
    <div id="spc-actors-feed"><p class="muted">No activity yet.</p></div>
    <p class="muted">Echte signalen alleen: een NPC is working als er een taak voor hem/haar in de queue staat, anders idle. Loop erheen (loop binnen 100 eenheden) en praat via de balk.</p></div>
    <div class="panel"><h2>Bureau</h2>
    <div id="spc-autonomy"><p class="muted">Dial laden…</p></div>
    <div id="spc-delegate"><p><b>Delegeer</b>
    <select id="spc-del-npc" aria-label="NPC">
    <option value="mos">Mos</option>
    <option value="oracle">Orakel</option>
    <option value="smid">Smid</option>
    <option value="archivaris">Archivaris</option>
    <option value="voorman" selected>Voorman</option>
    <option value="seinwachter">Seinwachter</option>
    </select>
    <input id="spc-del-req" type="text" placeholder="Vraag om werk, bijv. zoek uit… (max 500)" aria-label="Werkverzoek" autocomplete="off">
    <button id="spc-del-go" type="button">Vraag</button></p>
    <p class="muted" id="spc-del-note"></p></div>
    <div id="spc-bureau"><p class="muted">Geen voorstellen.</p></div>
    <p class="muted">Alleen letterlijk YES keurt goed; al het andere (ja, ok, YES!, leeg) wijst af. Status working in de stad volgt echte queue-taken.</p></div>
    <script type="application/json" id="spc-world">{world_json}</script>
    <script type="application/json" id="spc-actors">{actors_json}</script>
    <script type="importmap">{{"imports":{{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}}}</script>
    <script>{SOLARPUNK_JS}</script>
    <script>{SCAN_JS}</script>
    <script>{TOWN_JS}</script>
    <script>{ACTORS_JS}</script>
    <script>{BUREAU_JS}</script>
    <script type="module">
    import * as THREE from 'three';
    import {{OrbitControls}} from 'three/addons/controls/OrbitControls.js';
    {_HOMEBASE_JS}
    </script>
    {svg_map}
    {district_list}"""
    return _ui.shell("Solar Punk City", "/solarpunk", main, "")
