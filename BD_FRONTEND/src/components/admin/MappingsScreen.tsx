"use client";

/**
 * The reference mappings admin screen (task M2-B6, milestone/m2.md section 19).
 *
 * Needed so an admin can keep the industry and state mappings up to date without a code
 * change. It only switches between the two panels; every call and every rule lives in the
 * panels and on the server, which allows or refuses each request.
 */
import { useState } from "react";

import IndustryMappingsPanel from "@/components/admin/IndustryMappingsPanel";
import StateMappingsPanel from "@/components/admin/StateMappingsPanel";

type Tab = "industries" | "states";

/** Renders the two tabs and the chosen panel. */
export default function MappingsScreen() {
  const [tab, setTab] = useState<Tab>("industries");

  return (
    <section>
      <h1>Mappings</h1>
      <div className="row-actions" role="group" aria-label="Mapping type">
        <button
          className={tab === "industries" ? "button" : "button button-secondary"}
          type="button"
          aria-pressed={tab === "industries"}
          onClick={() => setTab("industries")}
        >
          Industries
        </button>
        <button
          className={tab === "states" ? "button" : "button button-secondary"}
          type="button"
          aria-pressed={tab === "states"}
          onClick={() => setTab("states")}
        >
          States
        </button>
      </div>
      {tab === "industries" ? <IndustryMappingsPanel /> : <StateMappingsPanel />}
    </section>
  );
}
