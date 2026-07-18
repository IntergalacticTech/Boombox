// VFD — vacuum-fluorescent display hi-fi. Dot-matrix + 7-seg glow on deep charcoal.
// VT323 pixel font, cyan-teal phosphor + amber secondary. Like a 1988 car stereo head unit scaled up.

const VFD = {
  bg:"#0b0d10", panel:"#101318", well:"#05070a",
  teal:"#6ff7e8", tealDim:"#1d4a45", amber:"#ffc257", amberDim:"#4a3617",
  ink2:"#3d4b52", red:"#ff6a5e", rule:"rgba(111,247,232,0.14)",
  font:"'VT323', monospace", mono:"'JetBrains Mono', monospace",
};

function VfdChrome({ children, mode="TAPE" }) {
  const t = useTicker(500);
  return (
    <div className="ab" style={{width:1280, height:800, background:VFD.bg, color:VFD.teal, fontFamily:VFD.font, position:"relative", overflow:"hidden"}}>
      <div style={{height:52, display:"flex", alignItems:"center", gap:20, padding:"0 24px",
        background:VFD.panel, borderBottom:`1px solid ${VFD.rule}`}}>
        <span style={{fontSize:26, letterSpacing:"0.14em", textShadow:`0 0 12px ${VFD.teal}`}}>◈ BOOMBOX-88</span>
        <span style={{fontSize:20, color:VFD.ink2}}>│</span>
        <span style={{fontSize:22, color:VFD.amber, letterSpacing:"0.2em", textShadow:`0 0 10px ${VFD.amber}66`}}>{mode}</span>
        <span style={{flex:1}}></span>
        {["DOLBY NR","CrO₂","48kHz"].map(s=>(
          <span key={s} style={{fontSize:18, color:VFD.tealDim, letterSpacing:"0.12em"}}>{s}</span>
        ))}
        <span style={{fontSize:22, color:VFD.teal, letterSpacing:"0.15em", textShadow:`0 0 10px ${VFD.teal}`}}>{t%2?"23:41":"23 41"}</span>
      </div>
      {children}
    </div>
  );
}

// Dot-matrix text: renders letters oversized in VT323 with a dot-grid mask overlay feel
function VfdDisplay({ children, size=64, color=VFD.teal, style }) {
  return (
    <div style={{fontFamily:VFD.font, fontSize:size, color, lineHeight:1,
      textShadow:`0 0 ${size/5}px ${color}88, 0 0 2px ${color}`, letterSpacing:"0.06em", ...style}}>
      {children}
    </div>
  );
}

// Segment-block level meter (classic VFD bars, rising columns)
function VfdMeter({ t, bands=14, seed=0, h=90 }) {
  return (
    <div style={{display:"flex", gap:5, alignItems:"flex-end", height:h}}>
      {Array.from({length:bands}).map((_,i)=>{
        const v = vu(t*0.7, i*0.6+seed);
        const rows = 8, lit = Math.round(v*rows);
        return (
          <div key={i} style={{display:"flex", flexDirection:"column-reverse", gap:3, flex:1}}>
            {Array.from({length:rows}).map((_,r)=>{
              const on = r < lit;
              const c = r >= rows-2 ? VFD.red : r >= rows-4 ? VFD.amber : VFD.teal;
              const dim = r >= rows-2 ? "#3a1a17" : r >= rows-4 ? VFD.amberDim : VFD.tealDim;
              return <div key={r} style={{height:(h-21)/rows, background:on?c:dim, opacity:on?1:0.35,
                boxShadow:on?`0 0 6px ${c}`:"none"}}/>;
            })}
          </div>
        );
      })}
    </div>
  );
}

function VfdBtn({ children, w=120, h=84, active, amber, onClick }) {
  const c = amber ? VFD.amber : VFD.teal;
  return (
    <button onClick={onClick} style={{
      width:w, height:h, background: active ? `${amber?"rgba(255,194,87,0.12)":"rgba(111,247,232,0.10)"}` : VFD.panel,
      border:`1px solid ${active?c:VFD.rule}`, borderRadius:6, color: active?c:VFD.tealDim,
      fontFamily:VFD.font, fontSize:22, letterSpacing:"0.12em", cursor:"pointer",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:2,
      textShadow: active?`0 0 10px ${c}`:"none",
      boxShadow: active?`0 0 18px ${c}33 inset`:"none", transition:"all .1s",
    }}>{children}</button>
  );
}

// ========== AUDIO ==========
function VfdAudio() {
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(80);
  const tr = TRACKS[7];
  return (
    <VfdChrome mode="TAPE ▶">
      <div style={{padding:"22px 26px", height:"calc(100% - 52px)", display:"flex", flexDirection:"column", gap:16}}>
        {/* Main display well */}
        <div style={{background:VFD.well, border:`1px solid ${VFD.rule}`, borderRadius:10, padding:"26px 30px", flex:1,
          display:"flex", flexDirection:"column", justifyContent:"space-between",
          backgroundImage:"radial-gradient(ellipse at 50% 0%, rgba(111,247,232,0.05), transparent 60%)"}}>
          <div style={{display:"flex", justifyContent:"space-between", alignItems:"flex-start"}}>
            <div>
              <div style={{fontSize:20, color:VFD.amber, letterSpacing:"0.25em", marginBottom:10, textShadow:`0 0 8px ${VFD.amber}66`}}>
                TRK 08 · LOCAL · A-SIDE
              </div>
              <VfdDisplay size={84}>{tr.title.toUpperCase()}</VfdDisplay>
              <VfdDisplay size={40} color={VFD.tealDim} style={{marginTop:10, textShadow:"none"}}>
                {tr.artist.toUpperCase()} — {tr.album.toUpperCase()}
              </VfdDisplay>
            </div>
            {/* 7-seg counter */}
            <div style={{textAlign:"right"}}>
              <div style={{fontSize:18, color:VFD.tealDim, letterSpacing:"0.3em", marginBottom:4}}>COUNTER</div>
              <VfdDisplay size={96} color={VFD.amber}>03:16</VfdDisplay>
              <div style={{fontSize:22, color:VFD.tealDim, marginTop:4}}>−{mmss(tr.len-196)} REMAIN</div>
            </div>
          </div>
          {/* meter + progress */}
          <div style={{display:"flex", gap:30, alignItems:"flex-end"}}>
            <div style={{flex:1}}>
              <VfdMeter t={t} bands={24} h={110}/>
            </div>
            <div style={{width:360}}>
              <div style={{display:"flex", justifyContent:"space-between", fontSize:18, color:VFD.tealDim, marginBottom:6}}>
                <span>TAPE POSITION</span><span style={{color:VFD.teal}}>59%</span>
              </div>
              <div style={{display:"flex", gap:3}}>
                {Array.from({length:30}).map((_,i)=>(
                  <div key={i} style={{flex:1, height:16, background: i<18 ? VFD.teal : VFD.tealDim,
                    opacity:i<18?1:0.35, boxShadow:i<18?`0 0 5px ${VFD.teal}`:"none"}}/>
                ))}
              </div>
            </div>
          </div>
        </div>
        {/* Transport row */}
        <div style={{display:"flex", gap:12, alignItems:"center"}}>
          <VfdBtn w={120} h={96}>◀◀<span style={{fontSize:15, color:"inherit"}}>REW</span></VfdBtn>
          <VfdBtn w={190} h={96} active amber onClick={()=>setPlaying(!playing)}>
            <span style={{fontSize:40}}>{playing?"▮▮":"▶"}</span>
            <span style={{fontSize:16}}>{playing?"PAUSE":"PLAY"}</span>
          </VfdBtn>
          <VfdBtn w={120} h={96}>▶▶<span style={{fontSize:15}}>FFW</span></VfdBtn>
          <VfdBtn w={100} h={96}>⇄<span style={{fontSize:15}}>SHUF</span></VfdBtn>
          <VfdBtn w={100} h={96}>↻<span style={{fontSize:15}}>RPT</span></VfdBtn>
          <span style={{flex:1}}></span>
          <div style={{background:VFD.panel, border:`1px solid ${VFD.rule}`, borderRadius:6, padding:"12px 18px", height:96, width:300, display:"flex", flexDirection:"column", justifyContent:"center", gap:8}}>
            <div style={{display:"flex", justifyContent:"space-between", fontSize:18, color:VFD.tealDim}}>
              <span>VOLUME</span><span style={{color:VFD.amber, textShadow:`0 0 8px ${VFD.amber}66`}}>62</span>
            </div>
            <div style={{display:"flex", gap:3}}>
              {Array.from({length:20}).map((_,i)=>(
                <div key={i} style={{flex:1, height:18, background:i<12?VFD.amber:VFD.amberDim, opacity:i<12?1:0.4,
                  boxShadow:i<12?`0 0 5px ${VFD.amber}`:"none"}}/>
              ))}
            </div>
          </div>
        </div>
      </div>
    </VfdChrome>
  );
}

// ========== SOURCE ==========
function VfdSource() {
  const [sel, setSel] = React.useState(0);
  return (
    <VfdChrome mode="INPUT">
      <div style={{padding:"24px 26px", height:"calc(100% - 52px)", display:"flex", flexDirection:"column", gap:16}}>
        <div style={{background:VFD.well, border:`1px solid ${VFD.rule}`, borderRadius:10, padding:"20px 28px"}}>
          <div style={{fontSize:20, color:VFD.tealDim, letterSpacing:"0.3em"}}>FUNCTION SELECT</div>
          <VfdDisplay size={72} color={VFD.amber}>{SOURCES[sel].label}</VfdDisplay>
          <div style={{fontSize:26, color:VFD.tealDim, marginTop:4}}>{SOURCES[sel].sub.toUpperCase()}</div>
        </div>
        <div style={{display:"grid", gridTemplateColumns:"repeat(3,1fr)", gridAutoRows:"1fr", gap:14, flex:1}}>
          {SOURCES.map((s,i)=>{
            const active = i===sel;
            return (
              <button key={s.id} onClick={()=>setSel(i)} style={{
                background: active?VFD.well:VFD.panel, border:`1px solid ${active?VFD.teal:VFD.rule}`,
                borderRadius:10, cursor:"pointer", color:active?VFD.teal:VFD.tealDim,
                fontFamily:VFD.font, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:10,
                boxShadow: active?`0 0 24px ${VFD.teal}22 inset, 0 0 20px ${VFD.teal}22`:"none",
                textShadow: active?`0 0 12px ${VFD.teal}`:"none", transition:"all .12s",
              }}>
                <Icon name={s.icon} size={52} stroke={active?VFD.teal:VFD.ink2} sw={1.6}/>
                <span style={{fontSize:34, letterSpacing:"0.14em"}}>{s.label}</span>
                <span style={{fontSize:18, color:active?VFD.amber:VFD.ink2, letterSpacing:"0.2em"}}>
                  {active?"● SELECTED":`F${i+1}`}
                </span>
              </button>
            );
          })}
        </div>
        <div style={{display:"flex", gap:12}}>
          <VfdBtn w={140} h={84} onClick={()=>setSel((sel+SOURCES.length-1)%SOURCES.length)}>◀ PREV</VfdBtn>
          <VfdBtn w={140} h={84} onClick={()=>setSel((sel+1)%SOURCES.length)}>NEXT ▶</VfdBtn>
          <span style={{flex:1}}></span>
          <VfdBtn w={220} h={84} active amber>ENTER ↵</VfdBtn>
        </div>
      </div>
    </VfdChrome>
  );
}

// ========== VIDEO ==========
function VfdVideo() {
  const [chrome, setChrome] = React.useState(true);
  const t = useTicker(80);
  return (
    <VfdChrome mode="VIDEO ▶">
      <div onClick={()=>setChrome(!chrome)} style={{position:"relative", height:"calc(100% - 52px)", background:"#000"}}>
        <div style={{position:"absolute", inset:0,
          background:"radial-gradient(ellipse at 45% 45%, rgba(111,247,232,0.12), transparent 45%), radial-gradient(circle at 70% 65%, rgba(255,194,87,0.10), transparent 45%), linear-gradient(180deg,#08131a,#000)"}}/>
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:10}}>
          <VfdDisplay size={26} color={VFD.amber}>OSD · PLAYBACK · 1080P</VfdDisplay>
          <VfdDisplay size={92}>AKIRA</VfdDisplay>
          <VfdDisplay size={30} color={VFD.tealDim} style={{textShadow:"none"}}>01:24:18 / 02:04:00 · CH.09</VfdDisplay>
        </div>
        {chrome && (
          <div style={{position:"absolute", left:0, right:0, bottom:0, padding:"18px 26px",
            background:"linear-gradient(0deg, rgba(0,0,0,0.9), transparent)"}}>
            <div style={{display:"flex", alignItems:"center", gap:14, marginBottom:12}}>
              <VfdDisplay size={26} color={VFD.amber}>01:24:18</VfdDisplay>
              <div style={{flex:1, display:"flex", gap:3}}>
                {Array.from({length:48}).map((_,i)=>(
                  <div key={i} style={{flex:1, height:14, background:i<33?VFD.teal:VFD.tealDim, opacity:i<33?1:0.35,
                    boxShadow:i<33?`0 0 4px ${VFD.teal}`:"none"}}/>
                ))}
              </div>
              <VfdDisplay size={26} color={VFD.tealDim} style={{textShadow:"none"}}>−39:42</VfdDisplay>
            </div>
            <div style={{display:"flex", gap:10}}>
              <VfdBtn w={100} h={76}>−10s</VfdBtn>
              <VfdBtn w={100} h={76}>◀◀</VfdBtn>
              <VfdBtn w={160} h={76} active amber><span style={{fontSize:30}}>▮▮</span></VfdBtn>
              <VfdBtn w={100} h={76}>▶▶</VfdBtn>
              <VfdBtn w={100} h={76}>+10s</VfdBtn>
              <span style={{flex:1}}></span>
              <VfdBtn w={130} h={76}>SUB EN</VfdBtn>
              <VfdBtn w={130} h={76}>AUD 5.1</VfdBtn>
            </div>
          </div>
        )}
      </div>
    </VfdChrome>
  );
}

Object.assign(window, { VfdAudio, VfdSource, VfdVideo });
