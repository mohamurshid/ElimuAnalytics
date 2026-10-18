import { Guard } from "@/components/Guard";
import { BottomNav, TopBar } from "@/components/TopBar";

/**
 * Every page in this group is behind the guard.
 *
 * Bottom padding on phones keeps the last row of a page clear of the fixed
 * tab bar; from md up the bar is gone and the padding returns to normal.
 */
export default function AppLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <Guard>
      <TopBar />
      <main className="mx-auto max-w-5xl px-4 pb-28 pt-6 md:pb-12 md:pt-8">
        {children}
      </main>
      <BottomNav />
    </Guard>
  );
}
