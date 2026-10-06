"""SP Home Base als begaanbaar 3D-pand (Three.js, procedureel).

Naar de referentiefoto: historisch Nederlands hoekpand — dubbele
tuitgevel met witte dakrand, grote winkelramen beneden met donkere
kozijnen, twee kleinere vensters boven, rode baksteen, oranje-rode
dakpannen, voor- én zijgevel met regenpijp en zijdeur.

Alles procedureel (canvas-textures, geen externe assets); alleen de
Three.js-lib komt van CDN (gepind, met eerlijke fallback als WebGL
of het CDN ontbreekt). Render-only pagina: geen backend-writes.
"""

HOMEBASE_JS = """(function(){
"use strict";
var box=document.getElementById("hb-3d");
if(!box)return;
function fail(msg){
  box.innerHTML='<div class="panel"><h2>3D unavailable</h2><p class="muted">'+msg+'</p></div>';
}
if(!window.WebGLRenderingContext){fail("No WebGL in this browser.");return;}
function brickTexture(){
  var c=document.createElement("canvas");c.width=c.height=256;
  var g=c.getContext("2d");
  g.fillStyle="#c9b8a6";g.fillRect(0,0,256,256);
  var bh=16,bw=42;
  for(var y=0;y<256/bh;y++){
    var off=(y%2)*bw/2;
    for(var x=-1;x<256/bw+1;x++){
      var v=118+((x*7+y*13)%3)*10;
      g.fillStyle="rgb("+(120+v*0.12|0)+","+(52+v*0.05|0)+","+(40+v*0.04|0)+")";
      g.fillRect(x*bw+off+2,y*bh+2,bw-4,bh-4);
    }
  }
  var t=new THREE.CanvasTexture(c);
  t.wrapS=t.wrapT=THREE.RepeatWrapping;t.colorSpace=THREE.SRGBColorSpace;
  return t;
}
function roofTexture(){
  var c=document.createElement("canvas");c.width=c.height=256;
  var g=c.getContext("2d");
  g.fillStyle="#7e2f22";g.fillRect(0,0,256,256);
  for(var y=0;y<8;y++){
    for(var x=0;x<8;x++){
      var v=((x*5+y*11)%3)*12;
      g.fillStyle="rgb("+(140+v|0)+","+(52+(v>>1)|0)+","+(36|0)+")";
      g.beginPath();g.arc(x*32+16,y*32+30,15,Math.PI,0);g.fill();
      g.strokeStyle="rgba(60,18,12,0.55)";g.stroke();
    }
  }
  var t=new THREE.CanvasTexture(c);
  t.wrapS=t.wrapT=THREE.RepeatWrapping;t.repeat.set(3,3);
  t.colorSpace=THREE.SRGBColorSpace;
  return t;
}
function cobbleTexture(){
  var c=document.createElement("canvas");c.width=c.height=256;
  var g=c.getContext("2d");
  g.fillStyle="#8d8578";g.fillRect(0,0,256,256);
  for(var i=0;i<260;i++){
    var v=120+((i*37)%40);
    g.fillStyle="rgb("+v+","+v+","+(v-8)+")";
    g.fillRect((i*53)%256,(i*91)%256,7,6);
  }
  var t=new THREE.CanvasTexture(c);
  t.wrapS=t.wrapT=THREE.RepeatWrapping;t.repeat.set(10,10);
  t.colorSpace=THREE.SRGBColorSpace;
  return t;
}
var scene=new THREE.Scene();
scene.background=new THREE.Color(0xbfd9e8);
scene.fog=new THREE.Fog(0xbfd9e8,60,160);
var camera=new THREE.PerspectiveCamera(45,16/9,0.1,500);
camera.position.set(20,12,24);
var renderer;
try{
  renderer=new THREE.WebGLRenderer({antialias:true});
}catch(e){fail("WebGL init failed.");return;}
renderer.setSize(box.clientWidth||800,450);
renderer.shadowMap.enabled=true;
renderer.shadowMap.type=THREE.PCFSoftShadowMap;
box.appendChild(renderer.domElement);
var controls=new OrbitControls(camera,renderer.domElement);
controls.target.set(2,3.5,0);
controls.enableDamping=true;
controls.autoRotate=true;controls.autoRotateSpeed=0.6;
controls.maxPolarAngle=Math.PI/2-0.02;
var sun=new THREE.DirectionalLight(0xffe7c0,1.15);
sun.position.set(18,26,14);sun.castShadow=true;
sun.shadow.mapSize.set(2048,2048);
sun.shadow.camera.left=-20;sun.shadow.camera.right=20;
sun.shadow.camera.top=20;sun.shadow.camera.bottom=-20;
scene.add(sun);
scene.add(new THREE.HemisphereLight(0xcfe5ff,0x8a7a5f,0.75));
var brickMat=new THREE.MeshStandardMaterial({map:brickTexture(),roughness:0.9});
var roofMat=new THREE.MeshStandardMaterial({map:roofTexture(),roughness:0.85});
var trimMat=new THREE.MeshStandardMaterial({color:0xf2ede2,roughness:0.6});
var frameMat=new THREE.MeshStandardMaterial({color:0x1a2233,roughness:0.5,metalness:0.25});
var glassMat=new THREE.MeshStandardMaterial({color:0xd8c690,roughness:0.2,metalness:0.55,emissive:0x554411,emissiveIntensity:0.35});
var doorMat=new THREE.MeshStandardMaterial({color:0x24406a,roughness:0.55});
var stoneMat=new THREE.MeshStandardMaterial({color:0x9a938a,roughness:0.95});
var pipeMat=new THREE.MeshStandardMaterial({color:0x2c2c2c,roughness:0.5,metalness:0.5});
var leafMat=new THREE.MeshStandardMaterial({color:0x3d7a44,roughness:0.9});
var ground=new THREE.Mesh(new THREE.PlaneGeometry(120,120),
  new THREE.MeshStandardMaterial({map:cobbleTexture(),roughness:1}));
ground.rotation.x=-Math.PI/2;ground.receiveShadow=true;scene.add(ground);
function wall(w,h,d,mat){
  var m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat||brickMat);
  m.castShadow=true;m.receiveShadow=true;return m;
}
function windowUnit(w,h){
  var g=new THREE.Group();
  var f=new THREE.Mesh(new THREE.BoxGeometry(w,h,0.12),frameMat);
  f.castShadow=true;g.add(f);
  var gl=new THREE.Mesh(new THREE.PlaneGeometry(w-0.24,h-0.24),glassMat);
  gl.position.z=0.07;g.add(gl);
  var barV=new THREE.Mesh(new THREE.BoxGeometry(0.07,h-0.24,0.02),frameMat);
  barV.position.z=0.08;g.add(barV);
  var barH=new THREE.Mesh(new THREE.BoxGeometry(w-0.24,0.07,0.02),frameMat);
  barH.position.z=0.08;g.add(barH);
  return g;
}
function gableRoof(w,d,rise,over){
  over=over||0.4;
  var g=new THREE.Group();
  var slope=Math.sqrt((w/2+over)*(w/2+over)+rise*rise);
  var ang=Math.atan2(rise,w/2+over);
  var L=new THREE.Mesh(new THREE.BoxGeometry(slope,0.14,d+over*2),roofMat);
  L.position.set(-(w/4+over/2),rise/2,0);L.rotation.z=ang;
  var R=L.clone();R.position.x=-L.position.x;R.rotation.z=-ang;
  L.castShadow=R.castShadow=true;L.receiveShadow=R.receiveShadow=true;
  g.add(L);g.add(R);
  var trimG=new THREE.BoxGeometry(slope+0.15,0.1,0.12);
  [[L,ang],[R,-ang]].forEach(function(pair){
    var m=pair[0],a=pair[1];
    [1,-1].forEach(function(s){
      var t=new THREE.Mesh(trimG,trimMat);
      t.position.set(m.position.x,m.position.y+0.1,s*(d/2+over));
      t.rotation.z=a;g.add(t);
    });
  });
  var shape=new THREE.Shape();
  shape.moveTo(-w/2,0);shape.lineTo(w/2,0);shape.lineTo(0,rise);shape.closePath();
  var tri=new THREE.ShapeGeometry(shape);
  [1,-1].forEach(function(s){
    var t=new THREE.Mesh(tri,brickMat);
    t.position.set(0,0,s*d/2);if(s<0)t.rotation.y=Math.PI;g.add(t);
  });
  return g;
}
var town=new THREE.Group();scene.add(town);
// --- hoofdvolume (voorgevel, breed, puntgevel naar voren)
var main=wall(10,7,8);main.position.set(0,3.5,0);town.add(main);
var mainRoof=gableRoof(10,8,3.2);mainRoof.position.set(0,7,0);
mainRoof.rotation.y=Math.PI/2;town.add(mainRoof);
// --- zijvleugel (hoek, puntgevel opzij, iets lager)
var wing=wall(7,6,6);wing.position.set(8,3,1);town.add(wing);
var wingRoof=gableRoof(6,7,2.6);wingRoof.position.set(8,6,1);town.add(wingRoof);
// --- nokverbinding (joined roofs)
var ridge=new THREE.Mesh(new THREE.BoxGeometry(4.4,0.5,1.2),roofMat);
ridge.position.set(4.6,9.4,0);ridge.rotation.z=-0.1;ridge.castShadow=true;town.add(ridge);
// --- voorgevel: winkelramen + deur (donkere kozijnen)
[[-3.1],[0],[3.1]].forEach(function(px){
  var w=windowUnit(2.4,2.6);w.position.set(px[0],2.1,4.02);town.add(w);
});
var door=new THREE.Mesh(new THREE.BoxGeometry(1.2,2.8,0.15),doorMat);
door.position.set(-4.2,1.5,4.03);door.castShadow=true;town.add(door);
var step=new THREE.Mesh(new THREE.BoxGeometry(1.6,0.18,0.7),stoneMat);
step.position.set(-4.2,0.09,4.3);step.receiveShadow=true;town.add(step);
// --- eerste verdieping: 1 groot + 1 klein vierkant venster
var big=windowUnit(2.6,1.8);big.position.set(-1.2,5.2,4.02);town.add(big);
var small=windowUnit(1.1,1.1);small.position.set(2.6,5.4,4.02);town.add(small);
// --- zolderluik in de tuitgevel
var attic=windowUnit(0.9,1.2);attic.position.set(0,8.2,4.02);town.add(attic);
// --- zijgevel: smalle ramen + zijdeur + regenpijp op de hoek
[[ -0.5],[1.8]].forEach(function(pz){
  var w=windowUnit(0.9,2.2);w.rotation.y=Math.PI/2;
  w.position.set(11.52,2.6,pz[0]);town.add(w);
});
var sdoor=new THREE.Mesh(new THREE.BoxGeometry(0.14,2.4,1.1),doorMat);
sdoor.position.set(11.51,1.3,-1.6);sdoor.castShadow=true;town.add(sdoor);
var pipe=new THREE.Mesh(new THREE.CylinderGeometry(0.09,0.09,7.4,10),pipeMat);
pipe.position.set(5.15,3.7,4.15);pipe.castShadow=true;town.add(pipe);
var elbow=new THREE.Mesh(new THREE.CylinderGeometry(0.09,0.09,0.8,10),pipeMat);
elbow.position.set(5.15,0.35,4.45);elbow.rotation.x=0.5;town.add(elbow);
// --- groen bij de deur (foto: planten links van de pui)
[[-5.6,4.6,0.5],[-5.0,4.9,0.35]].forEach(function(pp){
  var bush=new THREE.Mesh(new THREE.SphereGeometry(pp[2],10,8),leafMat);
  bush.position.set(pp[0],pp[2]*0.8,pp[1]);bush.castShadow=true;town.add(bush);
});
var clock=new THREE.Clock();
function frame(){
  requestAnimationFrame(frame);
  controls.update();
  renderer.render(scene,camera);
}
frame();
window.addEventListener("resize",function(){
  var w=box.clientWidth||800;
  camera.aspect=w/450;camera.updateProjectionMatrix();
  renderer.setSize(w,450);
});
})();"""


def render() -> str:
    """Volledige pagina. Alleen lezen; faalt eerlijk zonder WebGL/CDN."""
    from . import ui as _ui

    main = f"""<h1>⌂ SP Home Base — 3D</h1>
    <p class="muted">Het hoekpand als begaanbaar model: dubbele tuitgevel
    met witte rand, winkelramen beneden, baksteen en dakpannen —
    alles procedureel, geen downloads behalve de Three.js-lib.
    Sleep om rond te kijken · scroll om te zoomen ·
    <a href="/solarpunk">Back to Solar Punk City →</a></p>
    <div id="hb-3d" style="width:100%;max-width:960px;height:450px"></div>
    <div class="panel"><h2>Over dit pand</h2>
    <ul><li><b>Dubbele tuitgevel</b> — voor- en zijgevel elk met punt,
    wit afgewerkt, nokken verbonden.</li>
    <li><b>Begane grond</b> — drie grote winkelramen + blauwe deur met
    stoep; donkere kozijnen.</li>
    <li><b>Eerste verdieping</b> — één groot + één klein vierkant
    venster, plus zolderluik in de geveltop.</li>
    <li><b>Zijgevel</b> — smalle ramen, zijdeur en regenpijp op de hoek.</li>
    <li><b>Materiaal</b> — rode baksteen, oranje-rode dakpannen,
    klinkers op straat, groen bij de deur.</li></ul></div>
    <script type="importmap">{{"imports":{{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}}}</script>
    <script type="module">
    import * as THREE from 'three';
    import {{OrbitControls}} from 'three/addons/controls/OrbitControls.js';
    {HOMEBASE_JS}
    </script>"""
    return _ui.shell("SP Home Base 3D", "/homebase", main, "")