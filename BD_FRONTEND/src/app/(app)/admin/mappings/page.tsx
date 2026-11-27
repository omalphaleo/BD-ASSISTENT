/**
 * Mappings admin route (task M2-B6).
 *
 * Needed so the menu link "Mappings" opens the industry and state mapping admin. The page only
 * renders the client component; every rule and permission is enforced by the server.
 */
import MappingsScreen from "@/components/admin/MappingsScreen";

/** Renders the mappings admin screen. */
export default function MappingsPage() {
  return <MappingsScreen />;
}
