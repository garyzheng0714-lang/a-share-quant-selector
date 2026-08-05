import { ToastViewport } from "@astryxdesign/core/Toast";

/** The app-level toast surface is provided by Astryx. */
export function ToastContainer() {
  return <ToastViewport position="topEnd" maxVisible={4} inset={{ top: 16, end: 16 }} />;
}
