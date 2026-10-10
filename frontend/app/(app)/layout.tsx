import { Guard } from "@/components/Guard";
import { TopBar } from "@/components/TopBar";

/** Every page in this group is behind the guard. */
export default function AppLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <Guard>
      <TopBar />
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </Guard>
  );
}
