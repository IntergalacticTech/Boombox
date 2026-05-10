// TAPE//SHIFT — horizontal "reel" of sources/tracks. Cassette-as-data
// without drawing one. Strong horizontal motion, dense info bars at top/bottom,
// big focal "tape" in the middle. Color: warm graphite + ember + lime.

const TS = {
  bg:       "#161410",
  panel:    "#1f1c17",
  panelHi:  "#28241e",
  ink:      "#f3ece0",
  ink2:     "#a39684",
  rule:     "rgba(243,236,224,0.10)",
  ruleHi:   "rgba(243,236,224,0.18)",
  ember:    "#ff7a35",
  lime:     "#c8e44a",
  cyan:     "#7fd9d4",
  red:      "#ff5253",
  font:     "'Space Grotesk', system-ui, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function TsChrome({ children, label }) {
  return (
    <div className="ab" style={{
      width:1280, height:800, background:TS.bg, color:TS.ink, fontFamily:TS.font,
      position:"relative", overflow:"hidden",
    }}>
      <div style={{
        height:46, padding:"0 24px", display:"flex", alignItems:"center", gap:18,
        borderBottom:`1px solid ${TS.rule}`, fontFamily:TS.mono, fontSize:12,
        letterSpacing:"0.22em", textTransform:"uppercase", color:TS.ink2,
      }}>
        <span style={{color:TS.ember, fontWeight:700}}>▮▮▮</span>
        <span style={{color:TS.ink, fontWeight:700, letterSpacing:"0.32em"}}>TAPE//SHIFT</span>
        <span style={{color:TS.rule}}>│</span>
        <span>{label}</span>
        <span style={{flex:1}}></span>
        <span>SIDE A · {("0010").slice(0,4)}</span>
        <span style={{color:TS.rule}}>│</span>
        <span><span style={{color:TS.lime}}>●</span> LOCAL</span>
        <span style={{color:TS.rule}}>│</span>
        <span style={{fontVariantNumeric:"tabular-nums"}}>23:41</span>
      </div>
      {children}
    </div>
  );
}

function TsBtn({ children, w, h=92, primary, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      width: w || 110, height: h,
      background: primary ? TS.ember : (active ? TS.panelHi : TS.panel),
      color: primary ? "#1a0e08" : TS.ink,
      border:`1px solid ${primary ? TS.ember : TS.ruleHi}`,
      borderTop:`1px solid ${primary ? "#ffaa6a" : TS.ruleHi}`,
      borderBottom:`1px solid ${primary ? "#c54f10" : TS.rule}`,
      borderRadius:14,
      cursor:"pointer", fontFamily:TS.mono, fontSize:12, fontWeight:700,
      letterSpacing:"0.18em", textTransform:"uppercase",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:4,
      transition:"all .1s",
      boxShadow: primary ? "0 6px 0 #c54f10, 0 14px 24px rgba(255,122,53,0.3)" : "0 4px 0 rgba(0,0,0,0.4)",
    }}>{children}</button>
  );
}

// Horizontal reel — a strip of "tape segments" with the active one centered.
function ReelStrip({ items, activeIndex, getColor }) {
  const cardW = 240;
  const offset = -(activeIndex * (cardW + 14)) + (1232 - cardW) / 2;
  return (
    <div style={{position:"relative", height:160, overflow:"hidden"}}>
      {/* center playhead */}
      <div style={{position:"absolute", left:"50%", top:-6, bottom:-6, width:2, background:TS.ember, zIndex:2, boxShadow:`0 0 14px ${TS.ember}`}}/>
      <div style={{position:"absolute", left:"50%", top:-12, marginLeft:-10, width:20, height:8, background:TS.ember, clipPath:"polygon(0 0,100% 0,50% 100%)"}}/>
      <div style={{display:"flex", gap:14, transform:`translateX(${offset}px)`, transition:"transform .35s cubic-bezier(.4,1.4,.5,1)"}}>
        {items.map((it, i) => {
          const active = i === activeIndex;
          const c = getColor ? getColor(it, i) : TS.ember;
          return (
            <div key={i} style={{
              width:cardW, flex:`0 0 ${cardW}px`, height:160,
              background:active ? TS.panelHi : TS.panel,
              border:`1px solid ${active ? c : TS.ruleHi}`,
              borderRadius:14, padding:"14px 16px",
              opacity: active ? 1 : 0.55,
              transform: active ? "scale(1.0)" : "scale(0.92)",
              transition:"all .25s",
              display:"flex", flexDirection:"column", justifyContent:"space-between",
              position:"relative", overflow:"hidden",
            }}>
              {/* magnetic tape lines (decoration only — abstract) */}
              <div style={{position:"absolute", left:14, right:14, top:"50%",
                height:18, opacity: active ? 0.6 : 0.25,
                background: `repeating-linear-gradient(0deg, transparent 0 1px, ${c} 1px 2px, transparent 2px 4px)`}}/>
              <div style={{position:"relative", display:"flex", justifyContent:"space-between", alignItems:"center", fontFamily:TS.mono, fontSize:10, letterSpacing:"0.22em", color:c}}>
                <span>{String(i+1).padStart(2,"0")}</span>
                <span>{active ? "▶ NOW" : "○"}</span>
              </div>
              <div style={{position:"relative"}}>
                <div style={{fontFamily:TS.font, fontWeight:700, fontSize:18, lineHeight:1.1, letterSpacing:"-0.01em",
                  whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>
                  {it.title}
                </div>
                <div style={{fontFamily:TS.mono, fontSize:11, color:TS.ink2, marginTop:4, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>
                  {it.sub}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Stacked horizontal mini-spectrum (looks like a scrolling tape signal)
function TapeSignal({ height = 120 }) {
  const t = useTicker(60);
  const N = 220;
  return (
    <svg width="100%" viewBox={`0 0 ${N} ${height}`} preserveAspectRatio="none" style={{height, display:"block"}}>
      {/* center line */}
      <line x1="0" x2={N} y1={height/2} y2={height/2} stroke={TS.rule} strokeWidth="1"/>
      {/* signal */}
      {Array.from({length:N}).map((_,i)=>{
        const v = (vu(t*0.55, i*0.21) - 0.5);
        const h = Math.abs(v) * height * 0.85 + 1;
        return <rect key={i} x={i+0.4} y={height/2 - (v>0?h:0)} width={0.7} height={h}
          fill={v > 0.35 ? TS.ember : (v > 0 ? TS.lime : TS.cyan)}
          opacity={0.55 + Math.abs(v)*0.9}/>;
      })}
    </svg>
  );
}

// ========== AUDIO ==========
function TapeshiftAudio() {
  const [idx, setIdx] = React.useState(3);
  const [playing, setPlaying] = React.useState(true);
  const tr = TRACKS[idx];
  const reelItems = TRACKS.map(t => ({ title: t.title, sub: `${t.artist} · ${t.time}` }));
  const t = useTicker(80);

  return (
    <TsChrome label="01 · NOW PLAYING">
      {/* Top-left meta block + level meters */}
      <div style={{padding:"22px 24px 0", display:"grid", gridTemplateColumns:"1fr 360px", gap:24}}>
        <div>
          <div style={{fontFamily:TS.mono, fontSize:11, letterSpacing:"0.28em", color:TS.ember, marginBottom:8}}>
            ▶ TRACK · {String(idx+1).padStart(2,"0")} / {TRACKS.length}
          </div>
          <div style={{fontFamily:TS.font, fontSize:54, fontWeight:700, letterSpacing:"-0.03em", lineHeight:1}}>
            {tr.title}
          </div>
          <div style={{fontSize:20, color:TS.ink2, marginTop:8}}>
            <span style={{color:TS.ink}}>{tr.artist}</span>
            <span style={{margin:"0 10px", color:TS.rule}}>—</span>
            <em>{tr.album}</em>
          </div>
        </div>
        <div style={{background:TS.panel, border:`1px solid ${TS.rule}`, borderRadius:14, padding:"14px 16px"}}>
          <div style={{fontFamily:TS.mono, fontSize:10, letterSpacing:"0.22em", color:TS.ink2, marginBottom:10}}>
            LEVEL · L / R
          </div>
          {[1,2].map(s=>{
            const v = 0.5 + vu(t, s) * 0.45;
            const segs = 28;
            const fill = Math.round(v * segs);
            return (
              <div key={s} style={{display:"flex", alignItems:"center", gap:8, marginBottom:6}}>
                <span style={{fontFamily:TS.mono, fontSize:11, width:14, color:TS.ink2}}>{s===1?"L":"R"}</span>
                <div style={{flex:1, display:"flex", gap:2, height:14}}>
                  {Array.from({length:segs}).map((_,i)=>{
                    const c = i < segs*0.6 ? TS.lime : i < segs*0.85 ? TS.ember : TS.red;
                    return <div key={i} style={{flex:1, background: i < fill ? c : "rgba(255,255,255,0.04)"}}/>;
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Reel strip — the focal "tape" */}
      <div style={{padding:"22px 0", borderTop:`1px solid ${TS.rule}`, marginTop:18, background:`linear-gradient(180deg, ${TS.panel}, transparent 80%)`}}>
        <div style={{padding:"0 24px", fontFamily:TS.mono, fontSize:10, letterSpacing:"0.28em", color:TS.ink2, marginBottom:10, display:"flex", justifyContent:"space-between"}}>
          <span>◀ SIDE A · QUEUE ▶</span>
          <span style={{color:TS.ember}}>{tr.time}</span>
        </div>
        <ReelStrip items={reelItems} activeIndex={idx} getColor={() => TS.ember}/>
      </div>

      {/* Tape signal as progress visualization */}
      <div style={{padding:"0 24px 8px", marginTop:14}}>
        <div style={{position:"relative"}}>
          <TapeSignal height={70}/>
          {/* playhead */}
          <div style={{position:"absolute", left:"42%", top:-2, bottom:-2, width:2, background:TS.ink, boxShadow:`0 0 8px ${TS.ink}`}}/>
        </div>
        <div style={{display:"flex", justifyContent:"space-between", marginTop:6, fontFamily:TS.mono, fontSize:11, color:TS.ink2}}>
          <span style={{color:TS.ember, fontVariantNumeric:"tabular-nums"}}>03:16</span>
          <span style={{letterSpacing:"0.22em"}}>POSITION</span>
          <span style={{fontVariantNumeric:"tabular-nums"}}>−{mmss(tr.len - 196)}</span>
        </div>
      </div>

      {/* Transport tray */}
      <div style={{position:"absolute", left:24, right:24, bottom:18, display:"flex", gap:10, alignItems:"center"}}>
        <TsBtn w={104} h={88} onClick={()=>setIdx(Math.max(0, idx-1))}>
          <Icon name="prev" size={28} stroke={TS.ink}/>REW
        </TsBtn>
        <TsBtn w={180} h={88} primary onClick={()=>setPlaying(!playing)}>
          <Icon name={playing?"pause":"play"} size={36} stroke="#1a0e08"/>
          {playing ? "PAUSE" : "PLAY"}
        </TsBtn>
        <TsBtn w={104} h={88} onClick={()=>setIdx(Math.min(TRACKS.length-1, idx+1))}>
          <Icon name="next" size={28} stroke={TS.ink}/>FFW
        </TsBtn>
        <TsBtn w={88} h={88}><Icon name="shuffle" size={22} stroke={TS.ink}/></TsBtn>
        <TsBtn w={88} h={88}><Icon name="repeat" size={22} stroke={TS.ink}/></TsBtn>
        <div style={{flex:1}}></div>
        <div style={{display:"flex", alignItems:"center", gap:10, padding:"10px 14px", background:TS.panel,
          border:`1px solid ${TS.ruleHi}`, borderRadius:14, height:88, width:280}}>
          <Icon name="vol" size={22} stroke={TS.ink}/>
          <div style={{flex:1}}>
            <div style={{display:"flex", justifyContent:"space-between", fontFamily:TS.mono, fontSize:10, letterSpacing:"0.22em", color:TS.ink2, marginBottom:6}}>
              <span>VOL</span><span style={{color:TS.ember}}>62 · −14dB</span>
            </div>
            <div style={{height:8, background:"rgba(0,0,0,0.4)", borderRadius:4, position:"relative"}}>
              <div style={{height:"100%", width:"62%", background:TS.ember, borderRadius:4}}/>
            </div>
          </div>
        </div>
      </div>
    </TsChrome>
  );
}

// ========== SOURCE ==========
function TapeshiftSource() {
  const [sel, setSel] = React.useState(0);
  const colors = [TS.lime, TS.cyan, TS.ember, TS.ember, TS.lime, TS.cyan];
  const items = SOURCES.map((s, i) => ({ ...s, color: colors[i] }));

  return (
    <TsChrome label="02 · INPUT REEL">
      <div style={{padding:"32px 24px 0"}}>
        <div style={{fontFamily:TS.mono, fontSize:12, letterSpacing:"0.32em", color:TS.ember, marginBottom:12}}>
          ◀◀  SHIFT INPUT  ▶▶
        </div>
        <div style={{fontFamily:TS.font, fontSize:54, fontWeight:700, letterSpacing:"-0.03em", lineHeight:1}}>
          {items[sel].label.charAt(0) + items[sel].label.slice(1).toLowerCase()}
        </div>
        <div style={{fontSize:18, color:TS.ink2, marginTop:8}}>{items[sel].sub}</div>
      </div>

      {/* Bigger reel of sources */}
      <div style={{padding:"32px 0", marginTop:24, background:`linear-gradient(180deg, transparent, ${TS.panel} 30%, ${TS.panel} 70%, transparent)`}}>
        <div style={{padding:"0 24px", fontFamily:TS.mono, fontSize:10, letterSpacing:"0.28em", color:TS.ink2, marginBottom:14, display:"flex", justifyContent:"space-between"}}>
          <span>● SOURCE BANK</span>
          <span>← swipe / arrow keys →</span>
        </div>
        <div style={{position:"relative", height:240, overflow:"hidden"}}>
          <div style={{position:"absolute", left:"50%", top:-8, bottom:-8, width:2, background:TS.ember, zIndex:2, boxShadow:`0 0 14px ${TS.ember}`}}/>
          <div style={{display:"flex", gap:18, transform:`translateX(${-(sel*(280+18)) + (1280-280)/2}px)`, transition:"transform .35s cubic-bezier(.4,1.4,.5,1)"}}>
            {items.map((s, i) => {
              const active = i === sel;
              return (
                <button key={s.id} onClick={()=>setSel(i)} style={{
                  width:280, flex:`0 0 280px`, height:240,
                  background: active ? TS.panelHi : TS.bg,
                  border:`1px solid ${active ? s.color : TS.ruleHi}`,
                  borderRadius:18, padding:"22px 24px",
                  opacity: active ? 1 : 0.45,
                  transform: active ? "scale(1)" : "scale(0.88)",
                  transition:"all .25s",
                  display:"flex", flexDirection:"column", justifyContent:"space-between",
                  textAlign:"left", cursor:"pointer", color:TS.ink,
                  position:"relative", overflow:"hidden",
                  boxShadow: active ? `0 0 40px ${s.color}40` : "none",
                }}>
                  <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
                    <Icon name={s.icon} size={48} stroke={active ? s.color : TS.ink2} sw={1.6}/>
                    <span style={{fontFamily:TS.mono, fontSize:11, letterSpacing:"0.22em", color:active?s.color:TS.ink2}}>
                      {String(i+1).padStart(2,"0")} / {String(items.length).padStart(2,"0")}
                    </span>
                  </div>
                  <div>
                    <div style={{fontFamily:TS.font, fontWeight:700, fontSize:30, letterSpacing:"-0.02em", lineHeight:1}}>
                      {s.label}
                    </div>
                    <div style={{fontFamily:TS.mono, fontSize:12, color:TS.ink2, marginTop:8}}>
                      {s.sub}
                    </div>
                  </div>
                  {active && (
                    <div style={{position:"absolute", left:0, right:0, bottom:0, height:4, background: s.color, boxShadow:`0 0 14px ${s.color}`}}/>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Bottom transport */}
      <div style={{position:"absolute", left:24, right:24, bottom:18, display:"flex", gap:10, alignItems:"center"}}>
        <TsBtn w={120} h={88} onClick={()=>setSel(Math.max(0, sel-1))}>
          <Icon name="prev" size={28} stroke={TS.ink}/>SHIFT ◀
        </TsBtn>
        <TsBtn w={120} h={88} onClick={()=>setSel(Math.min(items.length-1, sel+1))}>
          <Icon name="next" size={28} stroke={TS.ink}/>SHIFT ▶
        </TsBtn>
        <div style={{flex:1}}></div>
        <TsBtn w={140} h={88}>BACK</TsBtn>
        <TsBtn w={220} h={88} primary>
          ROUTE TO {items[sel].label}
        </TsBtn>
      </div>
    </TsChrome>
  );
}

// ========== VIDEO ==========
function TapeshiftVideo() {
  const [chrome, setChrome] = React.useState(true);
  return (
    <TsChrome label="03 · VIDEO">
      <div onClick={()=>setChrome(!chrome)} style={{position:"absolute", left:0, right:0, top:46, bottom:0, background:"#000"}}>
        {/* Fake video — desert palette */}
        <div style={{position:"absolute", inset:0,
          background:`radial-gradient(ellipse at 35% 60%, rgba(255,122,53,0.35), transparent 50%),
                      radial-gradient(circle at 75% 30%, rgba(127,217,212,0.18), transparent 45%),
                      linear-gradient(180deg, #2b1a0c, #000 80%)`}}/>
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:14, color:TS.ink}}>
          <div style={{fontFamily:TS.mono, fontSize:12, letterSpacing:"0.32em", color:TS.lime}}>FILM · 4K · 5.1 ATMOS</div>
          <div style={{fontFamily:TS.font, fontSize:84, fontWeight:700, letterSpacing:"-0.04em", lineHeight:0.9, textAlign:"center"}}>
            PARIS,<br/>TEXAS
          </div>
          <div style={{fontFamily:TS.mono, fontSize:14, letterSpacing:"0.22em", color:TS.ember}}>
            01:24:18  /  02:25:00
          </div>
        </div>

        {chrome && (
          <>
            <div style={{position:"absolute", top:12, left:24, right:24, display:"flex", alignItems:"center", gap:12, fontFamily:TS.mono, fontSize:11, letterSpacing:"0.22em", color:TS.ink}}>
              <button style={{padding:"6px 12px", background:TS.panel, border:`1px solid ${TS.ruleHi}`, borderRadius:999, color:TS.ink, fontFamily:TS.mono, fontSize:11, letterSpacing:"0.22em"}}>◀ LIBRARY</button>
              <span style={{flex:1}}></span>
              <span style={{padding:"6px 12px", background:"rgba(127,217,212,0.12)", border:`1px solid ${TS.cyan}`, color:TS.cyan, borderRadius:999}}>
                CASTING · LIVING ROOM TV
              </span>
            </div>

            <div style={{position:"absolute", left:24, right:24, bottom:18,
              background:"rgba(28,24,18,0.78)", backdropFilter:"blur(20px)",
              border:`1px solid ${TS.ruleHi}`, borderRadius:18, padding:"16px 20px"}}>
              {/* Scrub as a tape signal */}
              <div style={{position:"relative", height:32, marginBottom:10}}>
                <TapeSignal height={32}/>
                <div style={{position:"absolute", left:"56%", top:-2, bottom:-2, width:2, background:TS.ember, boxShadow:`0 0 10px ${TS.ember}`}}/>
              </div>
              <div style={{display:"flex", alignItems:"center", gap:10}}>
                <span style={{fontFamily:TS.mono, fontSize:13, fontVariantNumeric:"tabular-nums", color:TS.ember, width:80}}>01:24:18</span>
                <TsBtn w={88} h={76}><Icon name="back10" size={26} stroke={TS.ink}/>−10</TsBtn>
                <TsBtn w={88} h={76}><Icon name="prev" size={26} stroke={TS.ink}/></TsBtn>
                <TsBtn w={150} h={76} primary><Icon name="pause" size={32} stroke="#1a0e08"/>PAUSE</TsBtn>
                <TsBtn w={88} h={76}><Icon name="next" size={26} stroke={TS.ink}/></TsBtn>
                <TsBtn w={88} h={76}><Icon name="fwd10" size={26} stroke={TS.ink}/>+10</TsBtn>
                <span style={{flex:1}}></span>
                <TsBtn w={104} h={76}>CC EN</TsBtn>
                <TsBtn w={104} h={76}>5.1 DAC</TsBtn>
                <TsBtn w={88} h={76}>FULL ⛶</TsBtn>
              </div>
            </div>
          </>
        )}
      </div>
    </TsChrome>
  );
}

Object.assign(window, { TapeshiftAudio, TapeshiftSource, TapeshiftVideo });
