import { QrOverlay } from "./QrOverlay";
import { SleepOsd } from "./SleepOsd";
import { RecordIndicator } from "./RecordIndicator";
import { SourceInstructionOverlay } from "./SourceInstructionOverlay";
import { ShutdownOverlay } from "./ShutdownOverlay";
import { CacheAdoptOverlay } from "./CacheAdoptOverlay";
import { RfidBindOverlay } from "./RfidBindOverlay";

export function OverlayRoot() {
  return (
    <>
      <QrOverlay />
      <SleepOsd />
      <RecordIndicator />
      <SourceInstructionOverlay />
      <ShutdownOverlay />
      <CacheAdoptOverlay />
      <RfidBindOverlay />
    </>
  );
}
