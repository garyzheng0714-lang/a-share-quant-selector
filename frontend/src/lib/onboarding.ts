import { useState, useCallback } from "react";

const WELCOME_KEY = "qselect_ob_welcome_dismissed";
const GUIDE_KEY = "qselect_ob_guide_dismissed";

function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string): void {
  try {
    localStorage.setItem(key, "1");
  } catch {
    /* storage full or restricted */
  }
}

export function useOnboardingState() {
  const [welcomeDismissed, setWelcomeDismissed] = useState(() =>
    readFlag(WELCOME_KEY),
  );
  const [guideDismissed, setGuideDismissed] = useState(() =>
    readFlag(GUIDE_KEY),
  );

  const dismissWelcome = useCallback(() => {
    writeFlag(WELCOME_KEY);
    setWelcomeDismissed(true);
  }, []);

  const dismissGuide = useCallback(() => {
    writeFlag(GUIDE_KEY);
    setGuideDismissed(true);
  }, []);

  return { welcomeDismissed, guideDismissed, dismissWelcome, dismissGuide };
}
