import { QrOverlay } from "./QrOverlay";
import { SleepOsd } from "./SleepOsd";
import { RecordIndicator } from "./RecordIndicator";
import { SourceInstructionOverlay } from "./SourceInstructionOverlay";
import { ShutdownOverlay } from "./ShutdownOverlay";

export function OverlayRoot() {
  return (
    <>
      <QrOverlay />
      <SleepOsd />
      <RecordIndicator />
      <SourceInstructionOverlay />
      <ShutdownOverlay />
    </>
  );
}
