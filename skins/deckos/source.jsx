// DECK//OS — terminal/cyberpunk tape-deck terminal
// Monospace everywhere, brackets, ASCII bars, scanline ambience.
// Color: phosphor green on near-black with magenta + cyan accents.

const DECK = {
  bg:       "#0a0e0c",
  panel:    "#0f1614",
  panelHi:  "#152120",
  ink:      "#9bf2c0",   // phosphor green
  ink2:     "#5da78a",
  dim:      "#2c4a3f",
  mag:      "#ff4fa8",
  cyan:     "#5be9ff",
  amber:    "#ffb84d",
  red:      "#ff5566",
  rule:     "rgba(155,242,192,0.18)",
  font:     "'JetBrains Mono', 'Space Mono', ui-monospace, monospace",
};

function DeckChrome({ children, title="DECK//OS v0.4.1" }) {
  const t = useTicker(500);
  return (
    <div className="ab" style={{
      width:1280, height:800, background:DECK.bg, color:DECK.ink, fontFamily:DECK.font,
      position:"relative", overflow:"hidden",
      backgroundImage:
        "repeating-linear-gradient(0deg, rgba(155,242,192,0.025) 0 1px, transparent 1px 3px)," +
        "radial-gradient(ellipse at 50% 50%, rgba(155,242,192,0.06), transparent 70%)",
    }}>
      {/* Top status bar */}
      <div style={{
        height:44, display:"flex", alignItems:"center", padding:"0 20px", gap:24,
        borderBottom:`1px solid ${DECK.rule}`, background:DECK.panel,
        fontSize:13, letterSpacing:"0.08em", textTransform:"uppercase"
      }}>
        <span style={{color:DECK.mag, fontWeight:700}}>● {title}</span>
        <span style={{color:DECK.dim}}>│</span>
        <span style={{color:DECK.ink2}}>UPTIME 04:21:09</span>
        <span style={{color:DECK.dim}}>│</span>
        <span style={{color:DECK.ink2}}>DAC pcm5122 @ 48kHz/24b</span>
        <span style={{flex:1}}></span>
        <span style={{color:DECK.cyan}}>WIFI -52dBm</span>
        <span style={{color:DECK.dim}}>│</span>
        <span style={{color:DECK.amber, fontVariantNumeric:"tabular-nums"}}>
          {t % 2 ? "23:41:08" : "23:41:08_"}
        </span>
      </div>
      {children}
    </div>
  );
}

// ASCII-style horizontal bar with a peak char
function AsciiBar({ value, width = 36, color = DECK.ink, peakColor = DECK.mag, label }) {
  const fill = Math.round(value * width);
  const out = [];
  for (let i = 0; i < width; i++) {
    if (i < fill - 1)        out.push("█");
    else if (i === fill - 1) out.push("▓");
    else if (i === fill)     out.push("░");
    else                     out.push("·");
  }
  // peak indicator: lit cells before threshold use color, the rest dim
  return (
    <div style={{display:"flex", alignItems:"center", gap:10, fontFamily:DECK.font, fontSize:14, lineHeight:1}}>
      {label && <span style={{color:DECK.ink2, width:42}}>{label}</span>}
      <span style={{letterSpacing:"0.05em"}}>
        {out.map((ch, i) => (
          <span key={i} style={{
            color: i < fill ? (i > width*0.85 ? peakColor : color) : DECK.dim
          }}>{ch}</span>
        ))}
      </span>
    </div>
  );
}

// Big square button. Bracketed [ LABEL ] style. Glow on active.
function DeckBtn({ children, active, hot, big, onClick, w, h }) {
  const color = active ? DECK.mag : DECK.ink;
  return (
    <button onClick={onClick} style={{
      width: w || (big ? 168 : 110), height: h || (big ? 110 : 84),
      background: active ? "rgba(255,79,168,0.08)" : "rgba(155,242,192,0.04)",
      border:`1.5px solid ${active ? DECK.mag : DECK.rule}`,
      color, fontFamily:DECK.font, fontSize:big?16:13, fontWeight:700,
      letterSpacing:"0.12em", textTransform:"uppercase", cursor:"pointer",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:6,
      boxShadow: active ? `0 0 0 1px ${DECK.mag} inset, 0 0 24px rgba(255,79,168,0.25)` : "none",
      transition:"all .12s",
      borderRadius:2,
    }}>{children}</button>
  );
}

// ========== AUDIO NOW PLAYING ==========
function DeckosAudio() {
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(80);
  const track = TRACKS[0];
  const elapsed = 88 + (t * 0.08) % (track.len - 88);
  const pct = elapsed / track.len;

  // Spectrum bars
  const bars = Array.from({length: 64}, (_, i) => vu(t * 0.6, i * 0.5));
  const lpeak = vu(t, 0), rpeak = vu(t, 5);

  return (
    <DeckChrome title="DECK//OS · NOW PLAYING">
      <div style={{padding:"24px 28px", display:"grid", gridTemplateColumns:"1fr 360px", gap:28, height:"calc(100% - 44px)"}}>
        {/* Left: track + spectrum */}
        <div style={{display:"flex", flexDirection:"column", gap:18, minHeight:0}}>
          {/* Track ID block */}
          <div style={{border:`1px solid ${DECK.rule}`, padding:"18px 22px", background:DECK.panel}}>
            <div style={{fontSize:11, color:DECK.ink2, letterSpacing:"0.18em", marginBottom:10}}>
              ┌── TRACK 04 / 17 ── DEVICE:LOCAL ── 320kbps mp3
            </div>
            <div style={{fontSize:38, fontWeight:700, color:DECK.ink, lineHeight:1.05, letterSpacing:"-0.01em"}}>
              {track.title}<span style={{color:DECK.mag}}>_</span>
            </div>
            <div style={{fontSize:18, color:DECK.cyan, marginTop:6}}>
              {track.artist} <span style={{color:DECK.dim}}>//</span> <span style={{color:DECK.ink2}}>{track.album}</span>
            </div>
          </div>

          {/* Spectrum */}
          <div style={{border:`1px solid ${DECK.rule}`, padding:"14px 18px", background:DECK.panel, flex:1, display:"flex", flexDirection:"column"}}>
            <div style={{fontSize:11, color:DECK.ink2, letterSpacing:"0.18em", marginBottom:10}}>
              ── FFT 64-BAND ── PRE-EQ ──
            </div>
            <div style={{flex:1, display:"flex", alignItems:"flex-end", gap:3, paddingBottom:4}}>
              {bars.map((v, i) => {
                const h = 6 + v * 100;
                const hot = v > 0.85;
                return (
                  <div key={i} style={{
                    flex:1, height:`${h}%`,
                    background: hot ? DECK.mag : (v > 0.5 ? DECK.ink : DECK.ink2),
                    boxShadow: hot ? `0 0 8px ${DECK.mag}` : "none",
                    minHeight:2,
                  }}/>
                );
              })}
            </div>
            <div style={{display:"flex", justifyContent:"space-between", color:DECK.dim, fontSize:10, letterSpacing:"0.18em", marginTop:6}}>
              <span>20Hz</span><span>200</span><span>2k</span><span>20kHz</span>
            </div>
          </div>

          {/* Progress as ASCII bar */}
          <div style={{border:`1px solid ${DECK.rule}`, padding:"14px 18px", background:DECK.panel, fontFamily:DECK.font}}>
            <div style={{display:"flex", justifyContent:"space-between", fontSize:13, color:DECK.ink2, marginBottom:6}}>
              <span style={{color:DECK.amber, fontVariantNumeric:"tabular-nums"}}>{mmss(elapsed)}</span>
              <span style={{color:DECK.dim, fontSize:11, letterSpacing:"0.12em"}}>POSITION</span>
              <span style={{color:DECK.amber, fontVariantNumeric:"tabular-nums"}}>−{mmss(track.len - elapsed)}</span>
            </div>
            <AsciiBar value={pct} width={70} color={DECK.cyan} peakColor={DECK.mag} />
          </div>
        </div>

        {/* Right: meters + transport */}
        <div style={{display:"flex", flexDirection:"column", gap:14}}>
          <div style={{border:`1px solid ${DECK.rule}`, padding:"14px 18px", background:DECK.panel}}>
            <div style={{fontSize:11, color:DECK.ink2, letterSpacing:"0.18em", marginBottom:14}}>── VU // PEAK ──</div>
            <div style={{display:"flex", flexDirection:"column", gap:8}}>
              <AsciiBar value={lpeak} width={28} label="L"/>
              <AsciiBar value={rpeak} width={28} label="R"/>
            </div>
            <div style={{fontSize:11, color:DECK.dim, letterSpacing:"0.18em", marginTop:14, display:"flex", justifyContent:"space-between"}}>
              <span>−∞</span><span>−24</span><span>−12</span><span>−6</span><span>0</span><span style={{color:DECK.red}}>+3</span>
            </div>
          </div>

          {/* Transport */}
          <div style={{border:`1px solid ${DECK.rule}`, padding:18, background:DECK.panel, display:"grid", gridTemplateColumns:"1fr 1fr", gap:10}}>
            <DeckBtn>{"<<"}<span style={{fontSize:9, color:DECK.dim}}>PREV</span></DeckBtn>
            <DeckBtn>{">>"}<span style={{fontSize:9, color:DECK.dim}}>NEXT</span></DeckBtn>
            <div style={{gridColumn:"1 / -1"}}>
              <DeckBtn big w="100%" h={140} active={playing} onClick={()=>setPlaying(!playing)}>
                <span style={{fontSize:48, lineHeight:1}}>{playing ? "▮▮" : "▶"}</span>
                <span style={{fontSize:11, color:playing?DECK.mag:DECK.ink2, letterSpacing:"0.2em"}}>
                  {playing ? "[ PAUSE ]" : "[ PLAY ]"}
                </span>
              </DeckBtn>
            </div>
            <DeckBtn>SHUF<span style={{fontSize:9, color:DECK.dim}}>⇄</span></DeckBtn>
            <DeckBtn>RPT<span style={{fontSize:9, color:DECK.dim}}>↻</span></DeckBtn>
          </div>

          {/* Volume */}
          <div style={{border:`1px solid ${DECK.rule}`, padding:"14px 18px", background:DECK.panel}}>
            <div style={{fontSize:11, color:DECK.ink2, letterSpacing:"0.18em", marginBottom:10, display:"flex", justifyContent:"space-between"}}>
              <span>VOL</span><span style={{color:DECK.amber}}>−14 dB</span>
            </div>
            <AsciiBar value={0.62} width={28} color={DECK.cyan} peakColor={DECK.amber}/>
          </div>
        </div>
      </div>
    </DeckChrome>
  );
}

// ========== SOURCE SWITCHER ==========
function DeckosSource() {
  const [sel, setSel] = React.useState("local");
  return (
    <DeckChrome title="DECK//OS · INPUT.SELECT">
      <div style={{padding:"28px 32px", height:"calc(100% - 44px)", display:"flex", flexDirection:"column"}}>
        <div style={{fontSize:14, color:DECK.ink2, letterSpacing:"0.18em", marginBottom:24}}>
          $ <span style={{color:DECK.mag}}>boombox</span>:~ select-input <span style={{color:DECK.cyan}}>--list</span>
        </div>
        <div style={{display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gap:16, flex:1}}>
          {SOURCES.map((s, i) => {
            const active = sel === s.id;
            return (
              <button key={s.id} onClick={()=>setSel(s.id)} style={{
                background: active ? "rgba(255,79,168,0.08)" : DECK.panel,
                border:`1.5px solid ${active ? DECK.mag : DECK.rule}`,
                padding:"22px 24px", textAlign:"left", cursor:"pointer", color:DECK.ink,
                fontFamily:DECK.font, position:"relative",
                boxShadow: active ? `0 0 24px rgba(255,79,168,0.2)` : "none",
                display:"flex", flexDirection:"column", gap:10,
              }}>
                <div style={{display:"flex", alignItems:"center", justifyContent:"space-between"}}>
                  <span style={{fontSize:11, color:active?DECK.mag:DECK.ink2, letterSpacing:"0.18em"}}>
                    [ {String(i).padStart(2,"0")} ]
                  </span>
                  <span style={{fontSize:11, color:active?DECK.mag:DECK.dim, letterSpacing:"0.18em"}}>
                    {active ? "● ACTIVE" : "○ STANDBY"}
                  </span>
                </div>
                <div style={{fontSize:32, fontWeight:700, letterSpacing:"-0.01em", color:active?DECK.ink:DECK.ink}}>
                  {s.label}
                </div>
                <div style={{fontSize:13, color:DECK.ink2}}>
                  {s.sub}
                </div>
                <div style={{marginTop:"auto", borderTop:`1px solid ${DECK.rule}`, paddingTop:10, fontSize:11, color:DECK.dim, letterSpacing:"0.14em"}}>
                  <AsciiBar value={active ? 0.85 : 0.15 + i * 0.08} width={22} color={active?DECK.mag:DECK.ink2} peakColor={DECK.mag}/>
                </div>
              </button>
            );
          })}
        </div>
        <div style={{marginTop:24, display:"flex", gap:14, alignItems:"center"}}>
          <DeckBtn active>↵ CONFIRM</DeckBtn>
          <DeckBtn>ESC CANCEL</DeckBtn>
          <span style={{flex:1}}></span>
          <span style={{color:DECK.ink2, fontSize:13}}>
            <span style={{color:DECK.mag}}>{sel.toUpperCase()}</span> selected · stream will reroute on confirm
          </span>
        </div>
      </div>
    </DeckChrome>
  );
}

// ========== VIDEO ==========
function DeckosVideo() {
  const [showChrome, setShowChrome] = React.useState(true);
  const t = useTicker(60);
  return (
    <DeckChrome title="DECK//OS · VIDEO">
      <div style={{position:"relative", height:"calc(100% - 44px)", background:"#000"}}
           onClick={()=>setShowChrome(!showChrome)}>
        {/* Fake video — gradient + scanlines */}
        <div style={{position:"absolute", inset:0,
          background:`radial-gradient(circle at 30% 40%, rgba(91,233,255,0.2), transparent 40%),
                     radial-gradient(circle at 70% 60%, rgba(255,79,168,0.18), transparent 45%),
                     linear-gradient(180deg, #0a1422, #000)`,
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(155,242,192,0.04) 0 2px, transparent 2px 5px)",
        }}/>
        {/* Frame ID */}
        <div style={{position:"absolute", top:14, left:18, color:DECK.ink, fontSize:11, letterSpacing:"0.18em", opacity:0.9}}>
          ▢ STREAM 01 · 1080p · h264 · {t % 2 ? "REC" : "  "}
        </div>
        <div style={{position:"absolute", top:14, right:18, color:DECK.mag, fontSize:11, letterSpacing:"0.18em"}}>
          ● LIVE
        </div>

        {/* Centered title pretending to be a video card */}
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:14}}>
          <div style={{fontFamily:DECK.font, fontSize:13, color:DECK.cyan, letterSpacing:"0.3em"}}>// VIDEO PAYLOAD //</div>
          <div style={{fontFamily:DECK.font, fontSize:64, color:DECK.ink, letterSpacing:"-0.02em", fontWeight:700, textShadow:`0 0 24px ${DECK.ink}`}}>
            BLADE.RUNNER.2049
          </div>
          <div style={{fontFamily:DECK.font, fontSize:14, color:DECK.ink2, letterSpacing:"0.2em"}}>
            01:24:18  /  02:43:51   ·   chapter 14
          </div>
        </div>

        {/* Auto-hide chrome */}
        {showChrome && (
          <div style={{
            position:"absolute", left:0, right:0, bottom:0, padding:"22px 28px",
            background:"linear-gradient(0deg, rgba(0,0,0,0.85), transparent)",
            fontFamily:DECK.font,
          }}>
            <div style={{display:"flex", alignItems:"center", gap:12, marginBottom:12}}>
              <span style={{color:DECK.amber, fontSize:13, fontVariantNumeric:"tabular-nums"}}>01:24:18</span>
              <div style={{flex:1, height:6, background:"rgba(255,255,255,0.12)", position:"relative"}}>
                <div style={{position:"absolute", left:0, top:0, bottom:0, width:"51%", background:DECK.mag, boxShadow:`0 0 12px ${DECK.mag}`}}/>
                <div style={{position:"absolute", left:"51%", top:-4, width:2, height:14, background:DECK.ink}}/>
              </div>
              <span style={{color:DECK.amber, fontSize:13, fontVariantNumeric:"tabular-nums"}}>−01:19:33</span>
            </div>
            <div style={{display:"flex", gap:10, alignItems:"center"}}>
              <DeckBtn w={84} h={68}>{"<<"}</DeckBtn>
              <DeckBtn w={84} h={68}>−10s</DeckBtn>
              <DeckBtn w={140} h={68} active>{"▮▮"} PAUSE</DeckBtn>
              <DeckBtn w={84} h={68}>+10s</DeckBtn>
              <DeckBtn w={84} h={68}>{">>"}</DeckBtn>
              <span style={{flex:1}}></span>
              <DeckBtn w={120} h={68}>SUBS<span style={{fontSize:9}}>EN · ON</span></DeckBtn>
              <DeckBtn w={120} h={68}>AUDIO<span style={{fontSize:9}}>5.1 · DAC</span></DeckBtn>
              <DeckBtn w={84} h={68}>{"⛶"}</DeckBtn>
            </div>
          </div>
        )}
      </div>
    </DeckChrome>
  );
}

Object.assign(window, { DeckosAudio, DeckosSource, DeckosVideo });
