// SIMPLE — clean dark streaming-app vibe, with DECK//OS influence:
// monospace technical strings, bracketed labels, ASCII level meter, subtle
// scanline overlay, phosphor cyan as a third accent. Keeps the violet/blue
// /black palette and roomy layout, but reads more like a piece of equipment.

const SMP = {
  bg:        "#07060c",
  panel:     "#100d1c",
  panelHi:   "#181530",
  rule:      "rgba(255,255,255,0.08)",
  ruleHi:    "rgba(255,255,255,0.16)",
  ink:       "#f3f1ff",
  ink2:      "#9892b8",
  ink3:      "#5e597a",
  violet:    "#8b5cf6",
  blue:      "#3b82f6",
  glow:      "#a78bfa",
  cyan:      "#5be7ff",   // phosphor accent (Deck//OS influence)
  amber:     "#ffb84d",
  font:      "'Inter', system-ui, -apple-system, sans-serif",
  mono:      "'JetBrains Mono', monospace",
};

// Tiny ASCII bar segment string (Deck//OS-style)
function AsciiSeg({ value, width = 16, color = SMP.cyan }) {
  const fill = Math.round(value * width);
  const cells = [];
  for (let i = 0; i < width; i++) {
    if (i < fill - 1)        cells.push("█");
    else if (i === fill - 1) cells.push("▓");
    else if (i === fill)     cells.push("░");
    else                     cells.push("·");
  }
  return (
    <span style={{fontFamily:SMP.mono, fontSize:11, letterSpacing:"0.04em"}}>
      {cells.map((ch, i) => (
        <span key={i} style={{color: i < fill ? color : SMP.ink3}}>{ch}</span>
      ))}
    </span>
  );
}

function SmpFrame({ children, active = "home" }) {
  const t = useTicker(500);
  return (
    <div className="ab" style={{
      width:1280, height:800, background:SMP.bg, color:SMP.ink, fontFamily:SMP.font,
      position:"relative", overflow:"hidden", display:"flex",
    }}>
      {/* Subtle scanline overlay (Deck//OS influence) */}
      <div style={{position:"absolute", inset:0, pointerEvents:"none", zIndex:50,
        backgroundImage:"repeating-linear-gradient(0deg, rgba(255,255,255,0.018) 0 1px, transparent 1px 3px)"}}/>

      {/* Sidebar */}
      <div style={{width:240, background:SMP.panel, borderRight:`1px solid ${SMP.rule}`,
        display:"flex", flexDirection:"column", padding:"22px 16px", position:"relative"}}>
        <div style={{display:"flex", alignItems:"center", gap:10, marginBottom:8}}>
          <div style={{width:32, height:32, borderRadius:8,
            background:`linear-gradient(135deg, ${SMP.violet}, ${SMP.blue})`,
            boxShadow:`0 0 18px ${SMP.violet}40`}}/>
          <div>
            <div style={{fontSize:17, fontWeight:700, letterSpacing:"-0.01em"}}>Boombox</div>
            <div style={{fontFamily:SMP.mono, fontSize:9, color:SMP.cyan, letterSpacing:"0.18em"}}>
              v0.4.1 · {t % 2 ? "ONLINE" : "ONLINE_"}
            </div>
          </div>
        </div>

        <div style={{fontFamily:SMP.mono, fontSize:10, color:SMP.ink3, letterSpacing:"0.22em",
          margin:"22px 4px 8px"}}>// NAV</div>

        <div style={{display:"flex", flexDirection:"column", gap:2}}>
          {[
            {id:"home",     label:"Now Playing", icon:"play",    k:"01"},
            {id:"library",  label:"Library",     icon:"queue",   k:"02"},
            {id:"sources",  label:"Sources",     icon:"cast",    k:"03"},
            {id:"video",    label:"Video",       icon:"airplay", k:"04"},
            {id:"search",   label:"Search",      icon:"search",  k:"05"},
          ].map(item => {
            const on = item.id === active;
            return (
              <div key={item.id} style={{
                display:"flex", alignItems:"center", gap:12, padding:"11px 12px",
                borderRadius:10, background: on ? "rgba(139,92,246,0.15)" : "transparent",
                color: on ? SMP.ink : SMP.ink2, cursor:"pointer",
                fontSize:14, fontWeight: on ? 600 : 500, position:"relative",
                borderLeft: on ? `2px solid ${SMP.cyan}` : "2px solid transparent",
              }}>
                <Icon name={item.icon} size={18} stroke={on ? SMP.glow : SMP.ink2} sw={1.8}/>
                <span style={{flex:1}}>{item.label}</span>
                <span style={{fontFamily:SMP.mono, fontSize:10, color: on ? SMP.cyan : SMP.ink3, letterSpacing:"0.12em"}}>
                  {item.k}
                </span>
              </div>
            );
          })}
        </div>

        <div style={{marginTop:"auto", padding:"14px 10px", borderTop:`1px solid ${SMP.rule}`,
          fontFamily:SMP.mono, fontSize:10, color:SMP.ink3, letterSpacing:"0.08em"}}>
          <div style={{display:"flex", justifyContent:"space-between", color:SMP.ink2, marginBottom:6}}>
            <span>[ DAC ]</span>
            <span style={{color:SMP.cyan}}>● 48k/24b</span>
          </div>
          <div style={{display:"flex", justifyContent:"space-between", marginBottom:4}}>
            <span>[ CPU ]</span><span>{12 + (t%4)}%</span>
          </div>
          <div style={{display:"flex", justifyContent:"space-between"}}>
            <span>[ NET ]</span><span style={{color:SMP.cyan}}>−52dBm</span>
          </div>
        </div>
      </div>
      <div style={{flex:1, position:"relative", overflow:"hidden"}}>{children}</div>
    </div>
  );
}

function SmpBtn({ children, w, h=48, primary, ghost, onClick }) {
  return (
    <button onClick={onClick} style={{
      width:w, height:h, borderRadius:999, padding:"0 22px",
      background: primary ? SMP.ink : (ghost ? "transparent" : "rgba(255,255,255,0.06)"),
      color: primary ? SMP.bg : SMP.ink,
      border: ghost ? `1px solid ${SMP.ruleHi}` : "none",
      cursor:"pointer", fontSize:14, fontWeight:600, letterSpacing:"-0.005em",
      display:"inline-flex", alignItems:"center", justifyContent:"center", gap:8,
      transition:"all .12s",
    }}>{children}</button>
  );
}

function SmpCircleBtn({ children, size=56, primary, onClick }) {
  return (
    <button onClick={onClick} style={{
      width:size, height:size, borderRadius:"50%",
      background: primary ? "#fff" : "rgba(255,255,255,0.08)",
      color: primary ? SMP.bg : SMP.ink,
      border:"none", cursor:"pointer",
      display:"inline-flex", alignItems:"center", justifyContent:"center",
      transition:"all .12s",
      boxShadow: primary ? `0 0 32px rgba(167,139,250,0.45), 0 0 0 1px rgba(255,255,255,0.4) inset` : "none",
    }}>{children}</button>
  );
}

// Terminal-style status pill: bracketed mono label + value
function SmpStat({ label, value, color = SMP.ink2 }) {
  return (
    <div style={{display:"flex", alignItems:"center", gap:8, padding:"6px 12px",
      background:"rgba(0,0,0,0.4)", border:`1px solid ${SMP.rule}`, borderRadius:999,
      fontFamily:SMP.mono, fontSize:11, letterSpacing:"0.14em"}}>
      <span style={{color:SMP.ink3}}>[{label}]</span>
      <span style={{color}}>{value}</span>
    </div>
  );
}

// ========== AUDIO ==========
function SimpleAudio() {
  const [playing, setPlaying] = React.useState(true);
  const tr = TRACKS[5];
  const t = useTicker(80);
  const lvl = 0.5 + vu(t, 1) * 0.45;
  const rvl = 0.5 + vu(t, 2) * 0.45;

  return (
    <SmpFrame active="home">
      <div style={{position:"absolute", top:0, left:0, right:0, height:380,
        background:`linear-gradient(180deg, rgba(139,92,246,0.28) 0%, rgba(59,130,246,0.10) 40%, transparent 100%)`,
        pointerEvents:"none"}}/>
      <div style={{position:"relative", height:"100%", display:"flex", flexDirection:"column"}}>
        {/* topbar — terminal-style status row */}
        <div style={{padding:"18px 36px 14px", display:"flex", alignItems:"center", gap:10,
          borderBottom:`1px solid ${SMP.rule}`, fontFamily:SMP.mono}}>
          <div style={{display:"flex", gap:6}}>
            <button style={{width:34, height:34, borderRadius:"50%", background:"rgba(0,0,0,0.5)", border:`1px solid ${SMP.rule}`, color:SMP.ink, cursor:"pointer", fontSize:15}}>‹</button>
            <button style={{width:34, height:34, borderRadius:"50%", background:"rgba(0,0,0,0.5)", border:`1px solid ${SMP.rule}`, color:SMP.ink, cursor:"pointer", fontSize:15}}>›</button>
          </div>
          <SmpStat label="SRC"  value="LOCAL"            color={SMP.glow}/>
          <SmpStat label="OUT"  value="DAC pcm5122"      color={SMP.cyan}/>
          <SmpStat label="FMT"  value="MP3 320 · 48k"    color={SMP.ink2}/>
          <span style={{flex:1}}></span>
          <SmpStat label="WIFI" value="−52dBm"           color={SMP.cyan}/>
          <SmpStat label="UTC"  value={t % 2 ? "23:41:08" : "23:41:08_"} color={SMP.amber}/>
        </div>

        {/* hero */}
        <div style={{padding:"22px 36px 22px", display:"flex", gap:28, alignItems:"flex-end"}}>
          <div style={{width:220, height:220, borderRadius:14,
            background:`linear-gradient(135deg, ${SMP.violet} 0%, ${SMP.blue} 100%)`,
            boxShadow:`0 24px 60px rgba(0,0,0,0.6), 0 0 0 1px ${SMP.ruleHi}`,
            display:"flex", alignItems:"center", justifyContent:"center",
            position:"relative", overflow:"hidden"}}>
            <div style={{width:120, height:120, borderRadius:"50%", border:`6px solid rgba(255,255,255,0.85)`}}/>
            <div style={{position:"absolute", width:24, height:24, borderRadius:"50%", background:SMP.bg}}/>
            {/* corner code */}
            <div style={{position:"absolute", top:10, left:12, fontFamily:SMP.mono, fontSize:10,
              color:"rgba(255,255,255,0.85)", letterSpacing:"0.18em"}}>
              [ TR/04 ]
            </div>
          </div>
          <div style={{flex:1, paddingBottom:8, minWidth:0}}>
            <div style={{display:"flex", alignItems:"center", gap:10, marginBottom:14}}>
              <span style={{fontFamily:SMP.mono, fontSize:11, color:SMP.cyan, letterSpacing:"0.22em"}}>
                ▶ NOW PLAYING
              </span>
              <span style={{fontFamily:SMP.mono, fontSize:11, color:SMP.ink3, letterSpacing:"0.18em"}}>
                · TRACK 04 / 17 ·
              </span>
            </div>
            <div style={{fontSize:60, fontWeight:800, letterSpacing:"-0.03em", lineHeight:0.95, marginBottom:14,
              whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>
              {tr.title}<span style={{color:SMP.cyan}}>_</span>
            </div>
            <div style={{fontSize:15, color:SMP.ink2, display:"flex", alignItems:"center", gap:8, marginBottom:14, fontFamily:SMP.mono}}>
              <span style={{fontWeight:600, color:SMP.ink}}>{tr.artist}</span>
              <span style={{color:SMP.ink3}}>//</span>
              <span>{tr.album}</span>
              <span style={{color:SMP.ink3}}>//</span>
              <span>1992</span>
              <span style={{color:SMP.ink3}}>//</span>
              <span>{tr.time}</span>
            </div>
            {/* ASCII L/R level meter (Deck//OS influence) */}
            <div style={{display:"flex", alignItems:"center", gap:14, fontFamily:SMP.mono}}>
              <span style={{fontSize:11, color:SMP.ink3, letterSpacing:"0.18em"}}>L</span>
              <AsciiSeg value={lvl} width={28} color={SMP.cyan}/>
              <span style={{fontSize:11, color:SMP.ink3, letterSpacing:"0.18em", marginLeft:8}}>R</span>
              <AsciiSeg value={rvl} width={28} color={SMP.glow}/>
            </div>
          </div>
        </div>

        {/* up next list */}
        <div style={{padding:"0 36px", flex:1, minHeight:0, display:"flex", flexDirection:"column"}}>
          <div style={{display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:12}}>
            <div style={{display:"flex", alignItems:"baseline", gap:10}}>
              <span style={{fontFamily:SMP.mono, fontSize:11, color:SMP.cyan, letterSpacing:"0.22em"}}>// QUEUE</span>
              <span style={{fontSize:18, fontWeight:700, letterSpacing:"-0.01em"}}>Up Next</span>
            </div>
            <div style={{fontFamily:SMP.mono, fontSize:11, color:SMP.ink2, letterSpacing:"0.14em"}}>
              [ {String(TRACKS.slice(0,6).length).padStart(2,"0")} TRACKS · 21:31 TOTAL ]
            </div>
          </div>
          <div style={{flex:1, overflow:"hidden", display:"flex", flexDirection:"column", gap:2}}>
            {TRACKS.slice(0,6).map((t, i) => {
              const active = i === 0;
              return (
                <div key={i} style={{
                  display:"grid", gridTemplateColumns:"32px 36px 1fr 1fr 80px 60px", gap:14,
                  padding:"9px 14px", borderRadius:8, alignItems:"center",
                  background: active ? "rgba(139,92,246,0.10)" : "transparent",
                  fontSize:14,
                }}>
                  <span style={{color: active ? SMP.cyan : SMP.ink3, fontFamily:SMP.mono, fontSize:12, letterSpacing:"0.08em"}}>
                    {active ? "▶" : String(i+1).padStart(2,"0")}
                  </span>
                  <div style={{width:36, height:36, borderRadius:6,
                    background:`linear-gradient(135deg, hsl(${t.hue}, 70%, 55%), hsl(${(t.hue+40)%360}, 60%, 35%))`}}/>
                  <div style={{minWidth:0}}>
                    <div style={{fontWeight:600, color:active?SMP.glow:SMP.ink, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{t.title}</div>
                    <div style={{fontSize:12, color:SMP.ink2, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{t.artist}</div>
                  </div>
                  <div style={{color:SMP.ink2, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis", fontFamily:SMP.mono, fontSize:13}}>{t.album}</div>
                  <div style={{fontFamily:SMP.mono, fontSize:11, color:SMP.ink3, letterSpacing:"0.12em"}}>
                    {["MP3·320","FLAC","FLAC","WAV","MP3·320","FLAC"][i]}
                  </div>
                  <div style={{color:active?SMP.cyan:SMP.ink2, fontFamily:SMP.mono, fontSize:13, textAlign:"right", fontVariantNumeric:"tabular-nums"}}>{t.time}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* bottom player bar */}
        <div style={{padding:"14px 36px", borderTop:`1px solid ${SMP.rule}`,
          background:"rgba(7,6,12,0.85)", backdropFilter:"blur(12px)",
          display:"grid", gridTemplateColumns:"260px 1fr 260px", gap:24, alignItems:"center"}}>
          <div style={{display:"flex", alignItems:"center", gap:12, minWidth:0}}>
            <div style={{width:44, height:44, borderRadius:6,
              background:`linear-gradient(135deg, ${SMP.violet}, ${SMP.blue})`, flexShrink:0}}/>
            <div style={{minWidth:0}}>
              <div style={{fontSize:13, fontWeight:600, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{tr.title}</div>
              <div style={{fontSize:11, color:SMP.ink2, fontFamily:SMP.mono, letterSpacing:"0.06em"}}>{tr.artist}</div>
            </div>
          </div>

          <div style={{display:"flex", flexDirection:"column", alignItems:"center", gap:8}}>
            <div style={{display:"flex", alignItems:"center", gap:12}}>
              <SmpCircleBtn size={44}><Icon name="shuffle" size={18}/></SmpCircleBtn>
              <SmpCircleBtn size={48}><Icon name="prev" size={22}/></SmpCircleBtn>
              <SmpCircleBtn size={64} primary onClick={()=>setPlaying(!playing)}>
                <Icon name={playing?"pause":"play"} size={26} stroke={SMP.bg}/>
              </SmpCircleBtn>
              <SmpCircleBtn size={48}><Icon name="next" size={22}/></SmpCircleBtn>
              <SmpCircleBtn size={44}><Icon name="repeat" size={18}/></SmpCircleBtn>
            </div>
            <div style={{display:"flex", alignItems:"center", gap:10, width:"100%", maxWidth:480}}>
              <span style={{fontFamily:SMP.mono, fontSize:11, color:SMP.cyan, fontVariantNumeric:"tabular-nums", letterSpacing:"0.06em"}}>3:01</span>
              <div style={{flex:1, height:4, background:"rgba(255,255,255,0.12)", borderRadius:2, position:"relative"}}>
                <div style={{height:"100%", width:"55%",
                  background:`linear-gradient(90deg, ${SMP.violet}, ${SMP.blue})`, borderRadius:2}}/>
                <div style={{position:"absolute", left:"55%", top:-5, width:14, height:14, borderRadius:"50%", background:"#fff", transform:"translateX(-50%)"}}/>
              </div>
              <span style={{fontFamily:SMP.mono, fontSize:11, color:SMP.ink2, fontVariantNumeric:"tabular-nums", letterSpacing:"0.06em"}}>−2:30</span>
            </div>
          </div>

          <div style={{display:"flex", alignItems:"center", justifyContent:"flex-end", gap:10}}>
            <span style={{fontFamily:SMP.mono, fontSize:10, color:SMP.ink3, letterSpacing:"0.18em"}}>VOL</span>
            <Icon name="vol" size={18} stroke={SMP.ink2}/>
            <div style={{flex:1, maxWidth:140, height:4, background:"rgba(255,255,255,0.12)", borderRadius:2, position:"relative"}}>
              <div style={{height:"100%", width:"62%", background:SMP.glow, borderRadius:2}}/>
              <div style={{position:"absolute", left:"62%", top:-5, width:14, height:14, borderRadius:"50%", background:"#fff", transform:"translateX(-50%)"}}/>
            </div>
            <span style={{fontFamily:SMP.mono, fontSize:11, color:SMP.cyan, letterSpacing:"0.06em"}}>62</span>
          </div>
        </div>
      </div>
    </SmpFrame>
  );
}

// ========== SOURCE ==========
function SimpleSource() {
  const [sel, setSel] = React.useState("local");
  const t = useTicker(500);
  return (
    <SmpFrame active="sources">
      <div style={{position:"absolute", top:0, left:0, right:0, height:280,
        background:`linear-gradient(180deg, rgba(59,130,246,0.18), transparent)`, pointerEvents:"none"}}/>
      <div style={{position:"relative", height:"100%", padding:"32px 40px 28px", display:"flex", flexDirection:"column"}}>
        {/* mock command line header */}
        <div style={{fontFamily:SMP.mono, fontSize:13, marginBottom:14, color:SMP.ink2, letterSpacing:"0.04em"}}>
          <span style={{color:SMP.cyan}}>boombox</span><span style={{color:SMP.ink3}}>:~</span>
          <span style={{color:SMP.ink}}> $ </span>
          <span>route --select </span>
          <span style={{color:SMP.glow}}>--list-sources</span>
          <span style={{color:SMP.cyan, marginLeft:4}}>{t % 2 ? "▌" : " "}</span>
        </div>

        <div style={{fontSize:46, fontWeight:800, letterSpacing:"-0.03em", lineHeight:1, marginBottom:6}}>
          Where do you want sound from?
        </div>
        <div style={{fontSize:15, color:SMP.ink2, marginBottom:24, fontFamily:SMP.mono, letterSpacing:"0.02em"}}>
          // tap a source · or arrow keys + ↵
        </div>

        <div style={{display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gridAutoRows:"1fr", gap:16, flex:1}}>
          {SOURCES.map((s, i) => {
            const active = sel === s.id;
            return (
              <button key={s.id} onClick={()=>setSel(s.id)} style={{
                background: active
                  ? `linear-gradient(135deg, rgba(139,92,246,0.22), rgba(59,130,246,0.18))`
                  : SMP.panel,
                border:`1px solid ${active ? SMP.violet : SMP.rule}`,
                borderRadius:16, padding:"20px 22px", textAlign:"left",
                cursor:"pointer", color:SMP.ink,
                position:"relative", overflow:"hidden",
                display:"flex", flexDirection:"column", justifyContent:"space-between",
                transition:"all .15s",
                boxShadow: active ? `0 0 60px rgba(139,92,246,0.18)` : "none",
              }}>
                {/* corner ID like Deck//OS */}
                <div style={{position:"absolute", top:14, left:18, fontFamily:SMP.mono, fontSize:10,
                  letterSpacing:"0.22em", color: active ? SMP.cyan : SMP.ink3}}>
                  [ {String(i+1).padStart(2,"0")} ]
                </div>
                <div style={{display:"flex", justifyContent:"flex-end", alignItems:"flex-start"}}>
                  {active ? (
                    <div style={{display:"flex", alignItems:"center", gap:6, padding:"4px 10px",
                      borderRadius:999, background:"rgba(167,139,250,0.18)",
                      color:SMP.glow, fontSize:10, fontWeight:600, letterSpacing:"0.14em", fontFamily:SMP.mono}}>
                      <span style={{width:6, height:6, borderRadius:"50%", background:SMP.cyan}}/>
                      ● ACTIVE
                    </div>
                  ) : (
                    <div style={{padding:"4px 10px", borderRadius:999, background:"rgba(255,255,255,0.04)",
                      color:SMP.ink3, fontSize:10, fontWeight:600, letterSpacing:"0.14em", fontFamily:SMP.mono}}>
                      ○ STANDBY
                    </div>
                  )}
                </div>
                <div style={{display:"flex", alignItems:"flex-end", justifyContent:"space-between", gap:14}}>
                  <div>
                    <div style={{width:48, height:48, borderRadius:12, marginBottom:14,
                      background: active
                        ? `linear-gradient(135deg, ${SMP.violet}, ${SMP.blue})`
                        : "rgba(255,255,255,0.05)",
                      display:"flex", alignItems:"center", justifyContent:"center"}}>
                      <Icon name={s.icon} size={24} stroke={active ? "#fff" : SMP.ink2} sw={1.8}/>
                    </div>
                    <div style={{fontSize:24, fontWeight:700, letterSpacing:"-0.01em"}}>
                      {s.label.charAt(0) + s.label.slice(1).toLowerCase()}
                    </div>
                    <div style={{fontSize:12, color:SMP.ink2, marginTop:4, fontFamily:SMP.mono, letterSpacing:"0.02em"}}>{s.sub}</div>
                  </div>
                  {/* per-card mini level */}
                  <div style={{paddingBottom:6}}>
                    <AsciiSeg value={active ? 0.85 : 0.15 + i*0.07} width={10} color={active?SMP.cyan:SMP.ink3}/>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        <div style={{marginTop:20, display:"flex", alignItems:"center", gap:12}}>
          <SmpBtn ghost h={52}>ESC · Cancel</SmpBtn>
          <div style={{flex:1}}></div>
          <div style={{fontSize:12, color:SMP.ink2, fontFamily:SMP.mono, letterSpacing:"0.06em"}}>
            <span style={{color:SMP.ink3}}>[ SELECTED ]</span>
            <span style={{color:SMP.glow, fontWeight:600, marginLeft:8}}>{SOURCES.find(s=>s.id===sel).label}</span>
          </div>
          <SmpBtn primary h={52} w={200}>↵ Route audio</SmpBtn>
        </div>
      </div>
    </SmpFrame>
  );
}

// ========== VIDEO ==========
function SimpleVideo() {
  const [chrome, setChrome] = React.useState(true);
  const t = useTicker(500);
  return (
    <SmpFrame active="video">
      <div onClick={()=>setChrome(!chrome)} style={{position:"absolute", inset:0, background:"#000"}}>
        <div style={{position:"absolute", inset:0,
          background:`radial-gradient(ellipse at 50% 40%, rgba(139,92,246,0.30), transparent 50%),
                      radial-gradient(circle at 75% 70%, rgba(59,130,246,0.25), transparent 45%),
                      linear-gradient(180deg, #110a26, #000 80%)`}}/>
        {/* scanlines on the video field too */}
        <div style={{position:"absolute", inset:0, pointerEvents:"none",
          backgroundImage:"repeating-linear-gradient(0deg, rgba(255,255,255,0.025) 0 1px, transparent 1px 4px)"}}/>
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:14}}>
          <div style={{fontFamily:SMP.mono, fontSize:11, fontWeight:600, letterSpacing:"0.32em", color:SMP.cyan}}>
            // FILM · 1080P · 5.1
          </div>
          <div style={{fontSize:80, fontWeight:800, letterSpacing:"-0.03em", textAlign:"center", lineHeight:0.95,
            textShadow:`0 0 32px rgba(139,92,246,0.4)`}}>
            Lost in<br/>Translation
          </div>
          <div style={{fontFamily:SMP.mono, fontSize:13, color:SMP.ink2, letterSpacing:"0.18em"}}>
            01:24:18 / 01:42:00 · CHAPTER 14
          </div>
        </div>

        {chrome && (
          <>
            <div style={{position:"absolute", top:18, left:28, right:28, display:"flex", alignItems:"center", gap:10}}>
              <button style={{width:38, height:38, borderRadius:"50%",
                background:"rgba(0,0,0,0.6)", border:`1px solid ${SMP.rule}`, color:SMP.ink, cursor:"pointer", fontSize:17}}>‹</button>
              <SmpStat label="STREAM" value="01" color={SMP.cyan}/>
              <SmpStat label="CODEC"  value="h264 · AC3" color={SMP.ink2}/>
              <span style={{flex:1}}></span>
              <div style={{padding:"6px 14px", borderRadius:999,
                background:"rgba(139,92,246,0.18)", border:`1px solid ${SMP.violet}`,
                color:SMP.glow, fontSize:11, fontWeight:600, letterSpacing:"0.14em", fontFamily:SMP.mono,
                display:"flex", alignItems:"center", gap:8}}>
                <span style={{width:8, height:8, borderRadius:"50%", background:SMP.cyan, boxShadow:`0 0 10px ${SMP.cyan}`}}/>
                {t % 2 ? "● CASTING · LIVING ROOM TV" : "  CASTING · LIVING ROOM TV"}
              </div>
            </div>

            <div style={{position:"absolute", left:24, right:24, bottom:24,
              padding:"16px 22px", borderRadius:18,
              background:"rgba(16,13,28,0.78)", backdropFilter:"blur(20px)",
              border:`1px solid ${SMP.rule}`}}>
              <div style={{display:"flex", alignItems:"center", gap:14, marginBottom:14}}>
                <span style={{fontFamily:SMP.mono, fontSize:13, color:SMP.cyan, fontVariantNumeric:"tabular-nums", letterSpacing:"0.06em"}}>01:24:18</span>
                <div style={{flex:1, height:4, background:"rgba(255,255,255,0.14)", borderRadius:2, position:"relative"}}>
                  <div style={{height:"100%", width:"82%",
                    background:`linear-gradient(90deg, ${SMP.violet}, ${SMP.blue})`, borderRadius:2,
                    boxShadow:`0 0 12px ${SMP.glow}`}}/>
                  {/* tick marks every 10% — Deck//OS rigor */}
                  {Array.from({length:11}).map((_,i)=>(
                    <div key={i} style={{position:"absolute", left:`${i*10}%`, top:-3, width:1, height:10, background:"rgba(255,255,255,0.18)"}}/>
                  ))}
                  <div style={{position:"absolute", left:"82%", top:-6, width:16, height:16, borderRadius:"50%", background:"#fff", transform:"translateX(-50%)"}}/>
                </div>
                <span style={{fontFamily:SMP.mono, fontSize:13, color:SMP.ink2, fontVariantNumeric:"tabular-nums", letterSpacing:"0.06em"}}>−17:42</span>
              </div>
              <div style={{display:"flex", alignItems:"center", gap:10}}>
                <SmpCircleBtn size={48}><Icon name="back10" size={20}/></SmpCircleBtn>
                <SmpCircleBtn size={48}><Icon name="prev" size={22}/></SmpCircleBtn>
                <SmpCircleBtn size={64} primary><Icon name="pause" size={26} stroke={SMP.bg}/></SmpCircleBtn>
                <SmpCircleBtn size={48}><Icon name="next" size={22}/></SmpCircleBtn>
                <SmpCircleBtn size={48}><Icon name="fwd10" size={20}/></SmpCircleBtn>
                <div style={{flex:1}}></div>
                <SmpBtn ghost h={44}>[ CC · EN ]</SmpBtn>
                <SmpBtn ghost h={44}>[ 5.1 · DAC ]</SmpBtn>
                <SmpCircleBtn size={48}>⛶</SmpCircleBtn>
              </div>
            </div>
          </>
        )}
      </div>
    </SmpFrame>
  );
}

Object.assign(window, { SimpleAudio, SimpleSource, SimpleVideo });
