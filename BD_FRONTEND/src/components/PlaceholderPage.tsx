/**
 * Shared body of the empty screen shells (task B3).
 *
 * Needed so the seven routes exist and can be navigated now, while their real content arrives
 * in later milestones. It makes no API calls and holds no business rules.
 */

/** Renders a title and a note saying when the screen gets its content. */
export default function PlaceholderPage({
  title,
  availability,
}: Readonly<{ title: string; availability: string }>) {
  return (
    <section>
      <h1>{title}</h1>
      <p>This screen is a placeholder. {availability}</p>
    </section>
  );
}
