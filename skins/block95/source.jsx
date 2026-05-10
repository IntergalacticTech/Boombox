// BLOCK 95 — chunky 90s portable boombox plastic, FLAT.
// Magenta / cyan / yellow / black blocks. No drawn cassettes.
// Bold geometric sans, hard color blocking, screw-head dots as hint of chunk.

const B95 = {
  yellow:   "#ffd400",
  magenta:  "#ff2d8a",
  cyan:     "#00d3e6",
  blue:     "#1c2bff",
  black:    "#0c0c0c",
  white:    "#fafaf6",
  paper:    "#eee8d8",
  font:     "'Archivo Black', 'Inter', system-ui, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function B95Chrome({ children, header="NOW PLAYING" }) {
  return (
    <div className="ab" style={{
      width:1280, height:800, background:B95.black, color:B95.white,
      fontFamily:"'Inter', system-ui, sans-serif", overflow:"hidden", position:"relative",
    }}>
      <div style={{
        height:64, padding:"0 24px", display:"flex", alignItems:"center", gap:24,
        background:B95.yellow, color:B95.black, borderBottom:`6px solid ${B95.black}`,
      }}>
        <div style={{fontFamily:B95.font, fontSize:26, letterSpacing:"-0.02em"}}>BOOMBOX/95</div>
        <div style={{fontFamily:B95.mono, fontSize:13, fontWeight:600, letterSpacing:"0.18em", padding:"4px 10px", background:B95.black, color:B95.yellow}}>
          {header}
        </div>
        <div style={{flex:1}}></div>
        <div style={{display:"flex", gap:8, alignItems:"center", fontFamily:B95.mono, fontSize:13, fontWeight:700}}>
          <div style={{width:14, height:14, background:B95.magenta, border:`2px solid ${B95.black}`}}></div>
          <span>LOCAL</span>
          <span style={{margin:"0 8px"}}>·</span>
          <span>23:41</span>
        </div>
      </div>
      {children}
    </div>
  );
}

function B95Btn({ children, color = B95.white, fg = B95.black, w, h = 100, big, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      width: w || (big ? 220 : 132), height: big ? 140 : h,
      background: color, color: fg,
      border:"none", outline:`4px solid ${B95.black}`,
      outlineOffset:-4,
      cursor:"pointer", position:"relative",
      fontFamily:B95.font, fontSize:big?22:16, letterSpacing:"-0.01em",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:4,
      boxShadow: active ? `8px 8px 0 ${B95.magenta}` : `6px 6px 0 ${B95.black}`,
      transform: active ? "translate(2px, 2px)" : "translate(0,0)",
      transition:"transform .08s, box-shadow .08s",
    }}>{children}</button>
  );
}

// ========== AUDIO ==========
function Block95Audio() {
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(80);
  const tr = TRACKS[2];
  // 12-segment LED-style VU as colored squares
  const segs = (val) => Array.from({length:12}, (_,i) => i < Math.round(val*12));
  const lvu = segs(0.45 + vu(t,1) * 0.4);
  const rvu = segs(0.45 + vu(t,2) * 0.4);

  return (
    <B95Chrome header="01 NOW PLAYING">
      <div style={{padding:24, height:"calc(100% - 64px)", display:"grid", gridTemplateColumns:"1.1fr 1fr", gap:24}}>
        {/* Left: huge title block, magenta */}
        <div style={{display:"flex", flexDirection:"column", gap:18, minHeight:0}}>
          <div style={{flex:1, background:B95.magenta, color:B95.black, padding:"32px 32px",
            display:"flex", flexDirection:"column", justifyContent:"space-between", border:`6px solid ${B95.black}`}}>
            <div>
              <div style={{fontFamily:B95.mono, fontSize:13, fontWeight:700, letterSpacing:"0.22em"}}>
                TRACK 04 / 17 — LOCAL
              </div>
              <div style={{fontFamily:B95.font, fontSize:78, lineHeight:0.92, letterSpacing:"-0.04em", marginTop:14}}>
                {tr.title}
              </div>
            </div>
            <div>
              <div style={{fontFamily:B95.font, fontSize:30, lineHeight:1, letterSpacing:"-0.02em"}}>
                {tr.artist}
              </div>
              <div style={{fontFamily:B95.mono, fontSize:14, fontWeight:600, marginTop:6, letterSpacing:"0.04em"}}>
                {tr.album} · 1998
              </div>
            </div>
          </div>

          {/* Progress block - cyan */}
          <div style={{background:B95.cyan, color:B95.black, padding:"18px 22px", border:`6px solid ${B95.black}`}}>
            <div style={{display:"flex", justifyContent:"space-between", fontFamily:B95.mono, fontSize:14, fontWeight:700, marginBottom:10}}>
              <span>01:24</span>
              <span style={{letterSpacing:"0.22em"}}>—— PROGRESS ——</span>
              <span>−1:07</span>
            </div>
            <div style={{height:18, background:B95.black, position:"relative", padding:2}}>
              <div style={{height:"100%", width:"56%", background:`repeating-linear-gradient(90deg, ${B95.yellow} 0 14px, ${B95.cyan} 14px 16px)`}}/>
            </div>
          </div>
        </div>

        {/* Right: VU + transport */}
        <div style={{display:"flex", flexDirection:"column", gap:16}}>
          {/* VU as LED grid */}
          <div style={{background:B95.white, color:B95.black, padding:"18px 20px", border:`6px solid ${B95.black}`}}>
            <div style={{fontFamily:B95.font, fontSize:18, marginBottom:14, letterSpacing:"-0.01em"}}>VU LEVELS</div>
            {[{l:"L", a:lvu},{l:"R", a:rvu}].map((row,ri)=>(
              <div key={ri} style={{display:"flex", alignItems:"center", gap:10, marginBottom:8}}>
                <div style={{fontFamily:B95.font, fontSize:24, width:24}}>{row.l}</div>
                <div style={{flex:1, display:"grid", gridTemplateColumns:"repeat(12, 1fr)", gap:4}}>
                  {row.a.map((on,i)=>{
                    const c = i < 7 ? B95.cyan : i < 10 ? B95.yellow : B95.magenta;
                    return <div key={i} style={{height:22, background: on ? c : "#e6e2d2", border:`2px solid ${B95.black}`}}/>;
                  })}
                </div>
              </div>
            ))}
            <div style={{display:"grid", gridTemplateColumns:"repeat(12, 1fr)", gap:4, paddingLeft:34, marginTop:6,
              fontFamily:B95.mono, fontSize:9, fontWeight:700, color:B95.black, letterSpacing:"0.02em"}}>
              {["−40","","","−20","","","−12","−6","−3","0","+3",""].map((v,i)=>
                <div key={i} style={{textAlign:"center"}}>{v}</div>
              )}
            </div>
          </div>

          {/* Transport */}
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:14}}>
            <B95Btn color={B95.white} h={120}><Icon name="prev" size={36} stroke={B95.black} sw={2.5}/>PREV</B95Btn>
            <B95Btn big color={playing?B95.yellow:B95.cyan} active onClick={()=>setPlaying(!playing)}>
              <Icon name={playing?"pause":"play"} size={56} stroke={B95.black} sw={2.5}/>
              {playing ? "PAUSE" : "PLAY"}
            </B95Btn>
            <B95Btn color={B95.white} h={120}><Icon name="next" size={36} stroke={B95.black} sw={2.5}/>NEXT</B95Btn>
          </div>
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr 1fr", gap:10}}>
            <B95Btn color={B95.cyan} h={80} w={null}><Icon name="shuffle" size={24} stroke={B95.black} sw={2.5}/></B95Btn>
            <B95Btn color={B95.cyan} h={80} w={null}><Icon name="repeat" size={24} stroke={B95.black} sw={2.5}/></B95Btn>
            <B95Btn color={B95.magenta} h={80} w={null} fg={B95.white}><Icon name="queue" size={24} stroke={B95.white} sw={2.5}/></B95Btn>
            <B95Btn color={B95.magenta} h={80} w={null} fg={B95.white}><Icon name="search" size={24} stroke={B95.white} sw={2.5}/></B95Btn>
          </div>

          {/* Volume */}
          <div style={{background:B95.black, color:B95.yellow, padding:"14px 18px", border:`4px solid ${B95.yellow}`, display:"flex", alignItems:"center", gap:14}}>
            <span style={{fontFamily:B95.font, fontSize:20}}>VOL</span>
            <div style={{flex:1, display:"flex", gap:3}}>
              {Array.from({length:24}).map((_,i)=>(
                <div key={i} style={{flex:1, height:22, background: i < 15 ? B95.yellow : "#3a3a30"}}/>
              ))}
            </div>
            <span style={{fontFamily:B95.mono, fontSize:14, fontWeight:700, minWidth:48, textAlign:"right"}}>62%</span>
          </div>
        </div>
      </div>
    </B95Chrome>
  );
}

// ========== SOURCE ==========
function Block95Source() {
  const [sel, setSel] = React.useState("local");
  const colors = [B95.magenta, B95.cyan, B95.yellow, B95.blue, B95.white, B95.magenta];

  return (
    <B95Chrome header="02 INPUT">
      <div style={{padding:24, height:"calc(100% - 64px)", display:"flex", flexDirection:"column", gap:20}}>
        <div style={{fontFamily:B95.font, fontSize:46, letterSpacing:"-0.03em", lineHeight:1}}>
          PICK A<br/>SOURCE.
        </div>
        <div style={{display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gridAutoRows:"1fr", gap:18, flex:1}}>
          {SOURCES.map((s, i) => {
            const active = sel === s.id;
            const c = colors[i % colors.length];
            const fg = (c === B95.white || c === B95.yellow || c === B95.cyan) ? B95.black : B95.white;
            return (
              <button key={s.id} onClick={()=>setSel(s.id)} style={{
                background: active ? c : B95.black,
                color: active ? fg : c,
                border:`6px solid ${active ? B95.black : c}`,
                cursor:"pointer", padding:"20px 24px", textAlign:"left",
                fontFamily:B95.font, position:"relative",
                boxShadow: active ? `10px 10px 0 ${B95.yellow}` : `0 0 0 ${B95.black}`,
                transform: active ? "translate(-2px,-2px)" : "translate(0,0)",
                transition:"transform .12s, box-shadow .12s",
                display:"flex", flexDirection:"column", justifyContent:"space-between",
              }}>
                <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
                  <Icon name={s.icon} size={56} stroke={active?fg:c} sw={2.4}/>
                  <span style={{fontFamily:B95.mono, fontSize:14, fontWeight:700, letterSpacing:"0.18em"}}>
                    {String(i+1).padStart(2,"0")}
                  </span>
                </div>
                <div>
                  <div style={{fontSize:38, letterSpacing:"-0.03em", lineHeight:1}}>{s.label}</div>
                  <div style={{fontFamily:B95.mono, fontSize:13, fontWeight:600, marginTop:8, opacity: active?1:0.8}}>
                    {s.sub}
                  </div>
                </div>
                {active && (
                  <div style={{position:"absolute", top:-12, left:-12, background:B95.black, color:B95.yellow,
                    padding:"4px 10px", fontFamily:B95.mono, fontSize:12, fontWeight:700, letterSpacing:"0.18em",
                    border:`3px solid ${B95.yellow}`}}>● LIVE</div>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </B95Chrome>
  );
}

// ========== VIDEO ==========
function Block95Video() {
  const [chrome, setChrome] = React.useState(true);
  return (
    <B95Chrome header="03 VIDEO">
      <div style={{position:"relative", height:"calc(100% - 64px)", background:"#000"}}
           onClick={()=>setChrome(!chrome)}>
        <div style={{position:"absolute", inset:0,
          background:`linear-gradient(135deg, ${B95.blue} 0%, #06081f 60%, #000 100%)`}}/>
        {/* big punchy title card */}
        <div style={{position:"absolute", inset:0, display:"flex", alignItems:"center", justifyContent:"center"}}>
          <div style={{padding:"40px 60px", border:`8px solid ${B95.yellow}`, color:B95.yellow,
            fontFamily:B95.font, fontSize:90, letterSpacing:"-0.04em", textAlign:"center", lineHeight:0.9,
            background:"rgba(0,0,0,0.4)"}}>
            DUNE<br/>PART TWO
          </div>
        </div>
        <div style={{position:"absolute", top:18, left:24, fontFamily:B95.mono, fontSize:13, fontWeight:700, color:B95.white, letterSpacing:"0.22em"}}>
          ▶ PLAYING · 1080P · DOLBY
        </div>
        <div style={{position:"absolute", top:18, right:24, padding:"4px 12px", background:B95.magenta, color:B95.white,
          fontFamily:B95.mono, fontSize:12, fontWeight:700, letterSpacing:"0.22em"}}>CASTING TO LIVING ROOM</div>

        {chrome && (
          <div style={{position:"absolute", left:0, right:0, bottom:0, padding:24, background:B95.black, borderTop:`6px solid ${B95.yellow}`}}>
            <div style={{display:"flex", alignItems:"center", gap:14, marginBottom:14}}>
              <span style={{fontFamily:B95.mono, fontSize:14, fontWeight:700, color:B95.yellow}}>01:24:18</span>
              <div style={{flex:1, height:14, background:"#222", padding:0, position:"relative", border:`3px solid ${B95.yellow}`}}>
                <div style={{height:"100%", width:"77%", background:B95.yellow}}/>
                <div style={{position:"absolute", left:"77%", top:-6, width:14, height:22, background:B95.magenta, border:`3px solid ${B95.yellow}`}}/>
              </div>
              <span style={{fontFamily:B95.mono, fontSize:14, fontWeight:700, color:B95.yellow}}>−25:42</span>
            </div>
            <div style={{display:"flex", gap:12}}>
              <B95Btn color={B95.white} h={84} w={104}><Icon name="back10" size={28} stroke={B95.black} sw={2.5}/>−10</B95Btn>
              <B95Btn color={B95.white} h={84} w={104}><Icon name="prev" size={28} stroke={B95.black} sw={2.5}/></B95Btn>
              <B95Btn color={B95.yellow} h={84} w={180} active><Icon name="pause" size={36} stroke={B95.black} sw={2.5}/>PAUSE</B95Btn>
              <B95Btn color={B95.white} h={84} w={104}><Icon name="next" size={28} stroke={B95.black} sw={2.5}/></B95Btn>
              <B95Btn color={B95.white} h={84} w={104}><Icon name="fwd10" size={28} stroke={B95.black} sw={2.5}/>+10</B95Btn>
              <div style={{flex:1}}></div>
              <B95Btn color={B95.cyan} h={84} w={120}>CC EN</B95Btn>
              <B95Btn color={B95.cyan} h={84} w={120}>5.1</B95Btn>
              <B95Btn color={B95.magenta} h={84} w={104} fg={B95.white}>FULL</B95Btn>
            </div>
          </div>
        )}
      </div>
    </B95Chrome>
  );
}

Object.assign(window, { Block95Audio, Block95Source, Block95Video });
