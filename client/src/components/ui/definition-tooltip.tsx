"use client";

import { Tooltip } from "@base-ui/react/tooltip";
import { CircleHelp } from "lucide-react";

export function DefinitionTooltip({ label, description }: { label: string; description: string }) {
  return (
    <Tooltip.Provider>
      <Tooltip.Root>
        <Tooltip.Trigger className="definition-tooltip__trigger" aria-label={`${label}: ${description}`}>
          <span>{label}</span>
          <CircleHelp size={14} aria-hidden="true" />
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Positioner className="definition-tooltip__positioner" sideOffset={8}>
            <Tooltip.Popup className="definition-tooltip__popup">
              <Tooltip.Arrow className="definition-tooltip__arrow" />
              {description}
            </Tooltip.Popup>
          </Tooltip.Positioner>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
