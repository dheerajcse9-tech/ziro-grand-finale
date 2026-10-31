"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Student" },
  { href: "/teacher", label: "Teacher" },
  { href: "/admin", label: "Admin" },
  { href: "/agents", label: "Agent activity" },
  { href: "/demo", label: "Jury demo" },
  { href: "/evaluation", label: "Evaluation" },
];

export default function Shell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const path = usePathname();
  const active = (h: string) => (h === "/" ? path === "/" || path.startsWith("/learn") : path.startsWith(h));
  return (
    <>
      <header className="sticky top-0 z-20 border-b border-line bg-bg/90 backdrop-blur">
        <div className={`mx-auto flex h-14 items-center justify-between px-5 ${wide ? "max-w-[1500px]" : "max-w-6xl"}`}>
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-sm text-white">D</span>
            DoubtLoop <span className="font-normal text-muted">AI</span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className={`rounded-md px-3 py-1.5 ${active(n.href) ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-ink"}`}>
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className={`mx-auto w-full px-5 py-8 ${wide ? "max-w-[1500px]" : "max-w-6xl"}`}>{children}</main>
    </>
  );
}
