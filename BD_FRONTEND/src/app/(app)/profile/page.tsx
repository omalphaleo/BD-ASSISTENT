/**
 * Empty shell for the My profile screen (task B3).
 *
 * Needed so the route exists now; the profile screen needs the "my profile" API (backend task A7)
 * and is built after it.
 */
import PlaceholderPage from "@/components/PlaceholderPage";

/** Renders the placeholder for My profile. */
export default function ProfilePage() {
  return (
    <PlaceholderPage title="My profile" availability="The profile screen follows the user management API (A7)." />
  );
}
