/**
 * Empty shell for the Users screen (task B3).
 *
 * Needed so the route exists now; the admin user list and edit screens need the user management
 * API (backend task A7) and are built after it.
 */
import PlaceholderPage from "@/components/PlaceholderPage";

/** Renders the placeholder for Users. */
export default function UsersPage() {
  return (
    <PlaceholderPage
      title="Users"
      availability="The user list and edit screens follow the user management API (A7)."
    />
  );
}
