// App — wires the design canvas with all 11 directions × 3 artboards each:
// the 6 shipped skins plus 5 design-only explorations (VFD-88, Flight Deck,
// Midnight FM, Zine, Boom/OS) that have no runtime counterpart yet.

const { DesignCanvas, DCSection, DCArtboard, DCPostIt } = window;

function App() {
  return (
    <DesignCanvas>
      <DCPostIt top={20} left={28} width={420} rotate={-1.5}>
        <strong>Boombox UI · 11 directions</strong><br/>
        Each row is one direction with 3 artboards: <em>Now Playing (audio)</em>, <em>Source switcher</em>, <em>Now Playing (video)</em>.
        All sized to your 1280×800 touchscreen. Big buttons (≥72px hit) for gloves. Click any card's expand icon to focus it fullscreen.
      </DCPostIt>

      <DCSection id="simple" title="SIMPLE" subtitle="Streaming-app inspired · sidebar + content · violet/blue on black">
        <DCArtboard id="simple-audio"  label="Now Playing · Audio"  width={1280} height={800}>
          <SimpleAudio/>
        </DCArtboard>
        <DCArtboard id="simple-source" label="Source Switcher"      width={1280} height={800}>
          <SimpleSource/>
        </DCArtboard>
        <DCArtboard id="simple-video"  label="Now Playing · Video"  width={1280} height={800}>
          <SimpleVideo/>
        </DCArtboard>
      </DCSection>

      <DCSection id="vfd" title="VFD-88" subtitle="Vacuum-fluorescent hi-fi display · pixel glow · teal + amber phosphor">
        <DCArtboard id="vfd-audio"  label="Now Playing · Audio"  width={1280} height={800}><VfdAudio/></DCArtboard>
        <DCArtboard id="vfd-source" label="Source Switcher"      width={1280} height={800}><VfdSource/></DCArtboard>
        <DCArtboard id="vfd-video"  label="Now Playing · Video"  width={1280} height={800}><VfdVideo/></DCArtboard>
      </DCSection>

      <DCSection id="flight" title="FLIGHT DECK" subtitle="Avionics MFD · bezel softkeys both sides · vector-green arc gauges">
        <DCArtboard id="flight-audio"  label="Now Playing · Audio"  width={1280} height={800}><FlightAudio/></DCArtboard>
        <DCArtboard id="flight-source" label="Source Switcher"      width={1280} height={800}><FlightSource/></DCArtboard>
        <DCArtboard id="flight-video"  label="Now Playing · Video"  width={1280} height={800}><FlightVideo/></DCArtboard>
      </DCSection>

      <DCSection id="fm" title="MIDNIGHT FM" subtitle="Tuner-dial metaphor · tracks & sources live at frequencies · red needle">
        <DCArtboard id="fm-audio"  label="Now Playing · Audio"  width={1280} height={800}><FmAudio/></DCArtboard>
        <DCArtboard id="fm-source" label="Source Switcher"      width={1280} height={800}><FmSource/></DCArtboard>
        <DCArtboard id="fm-video"  label="Now Playing · Video"  width={1280} height={800}><FmVideo/></DCArtboard>
      </DCSection>

      <DCSection id="zine" title="ZINE" subtitle="Xerox punk paper · tape strips · stamps · halftone">
        <DCArtboard id="zine-audio"  label="Now Playing · Audio"  width={1280} height={800}><ZineAudio/></DCArtboard>
        <DCArtboard id="zine-source" label="Source Switcher"      width={1280} height={800}><ZineSource/></DCArtboard>
        <DCArtboard id="zine-video"  label="Now Playing · Video"  width={1280} height={800}><ZineVideo/></DCArtboard>
      </DCSection>

      <DCSection id="boomos" title="BOOM/OS" subtitle="Retro desktop OS · beveled windows · pinstripe title bars · player as apps">
        <DCArtboard id="boomos-audio"  label="Now Playing · Audio"  width={1280} height={800}><OsAudio/></DCArtboard>
        <DCArtboard id="boomos-source" label="Source Switcher"      width={1280} height={800}><OsSource/></DCArtboard>
        <DCArtboard id="boomos-video"  label="Now Playing · Video"  width={1280} height={800}><OsVideo/></DCArtboard>
      </DCSection>

      <DCSection id="deckos" title="DECK//OS" subtitle="Cyberpunk tape-deck terminal · phosphor green + magenta + ASCII bars">
        <DCArtboard id="deckos-audio"  label="Now Playing · Audio"  width={1280} height={800}>
          <DeckosAudio/>
        </DCArtboard>
        <DCArtboard id="deckos-source" label="Source Switcher"      width={1280} height={800}>
          <DeckosSource/>
        </DCArtboard>
        <DCArtboard id="deckos-video"  label="Now Playing · Video"  width={1280} height={800}>
          <DeckosVideo/>
        </DCArtboard>
      </DCSection>

      <DCSection id="meter" title="METER" subtitle="Vintage VU/gauge worship · twin needle meters · cream paper + safety amber">
        <DCArtboard id="meter-audio"  label="Now Playing · Audio"  width={1280} height={800}>
          <MeterAudio/>
        </DCArtboard>
        <DCArtboard id="meter-source" label="Source Switcher"      width={1280} height={800}>
          <MeterSource/>
        </DCArtboard>
        <DCArtboard id="meter-video"  label="Now Playing · Video"  width={1280} height={800}>
          <MeterVideo/>
        </DCArtboard>
      </DCSection>

      <DCSection id="block95" title="BLOCK 95" subtitle="Chunky 90s portable boombox plastic · magenta / cyan / yellow / black blocks · flat">
        <DCArtboard id="block95-audio"  label="Now Playing · Audio"  width={1280} height={800}>
          <Block95Audio/>
        </DCArtboard>
        <DCArtboard id="block95-source" label="Source Switcher"      width={1280} height={800}>
          <Block95Source/>
        </DCArtboard>
        <DCArtboard id="block95-video"  label="Now Playing · Video"  width={1280} height={800}>
          <Block95Video/>
        </DCArtboard>
      </DCSection>

      <DCSection id="spectrum" title="SPECTRUM" subtitle="Visualizer-first immersive · radial spectrum + glass tray transport">
        <DCArtboard id="spectrum-audio"  label="Now Playing · Audio"  width={1280} height={800}>
          <SpectrumAudio/>
        </DCArtboard>
        <DCArtboard id="spectrum-source" label="Source Switcher"      width={1280} height={800}>
          <SpectrumSource/>
        </DCArtboard>
        <DCArtboard id="spectrum-video"  label="Now Playing · Video"  width={1280} height={800}>
          <SpectrumVideo/>
        </DCArtboard>
      </DCSection>

      <DCSection id="tapeshift" title="TAPE//SHIFT" subtitle="Horizontal reel of sources/tracks · cassette-as-data without drawing one">
        <DCArtboard id="tapeshift-audio"  label="Now Playing · Audio"  width={1280} height={800}>
          <TapeshiftAudio/>
        </DCArtboard>
        <DCArtboard id="tapeshift-source" label="Source Switcher"      width={1280} height={800}>
          <TapeshiftSource/>
        </DCArtboard>
        <DCArtboard id="tapeshift-video"  label="Now Playing · Video"  width={1280} height={800}>
          <TapeshiftVideo/>
        </DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
