/**
 * The status badges and flags of one result row (task M3-A3).
 *
 * Needed so each lead shows the five approved badges (cooling off, replied, possible duplicate,
 * unverified email, opted out; D-067, D-106) and its status flags in one consistent, colour-coded
 * way: red for opted out, amber for cautions, blue for cooling off, green for flags.
 * The server decides which apply; this only turns them into words and colours.
 */
import styles from "@/components/search/search.module.css";
import type { Badge, LeadStatusFlagType } from "@/lib/api/types.gen";
import { FLAG_LABELS } from "@/lib/search/filters";
import { BADGE_LABELS, EMPTY_CELL } from "@/lib/search/format";

/** Extra colour class per badge (how serious it is for outreach); a neutral badge adds none. */
const BADGE_TONE: Record<Badge, string> = {
  opted_out: styles.badgeDanger,
  replied: styles.badgeWarn,
  possible_duplicate: styles.badgeWarn,
  unverified_email: "",
  cooling_off: styles.badgeInfo,
};

/** Renders the flags and badges, or a dash when there are none. */
export default function BadgeList({
  badges,
  flags,
}: Readonly<{ badges: readonly Badge[]; flags: readonly LeadStatusFlagType[] }>) {
  if (badges.length === 0 && flags.length === 0) return <span className={styles.dim}>{EMPTY_CELL}</span>;
  return (
    <div className={styles.badges}>
      {flags.map((flag) => (
        <span className={`${styles.badge} ${styles.badgeOk}`} key={flag}>
          {FLAG_LABELS[flag]}
        </span>
      ))}
      {badges.map((badge) => (
        <span className={`${styles.badge} ${BADGE_TONE[badge]}`} key={badge}>
          {BADGE_LABELS[badge]}
        </span>
      ))}
    </div>
  );
}
