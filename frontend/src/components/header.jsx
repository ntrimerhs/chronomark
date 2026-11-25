import '../styles/header.css';
import { ArrowUpRight } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import CommandPalette from './CommandPalette';

/* The navigation, to the hero reference: the mark stays the supplied artwork,
   the name is set as spaced uppercase type beside it, and the sections are
   divided by hairlines rather than boxes.

   The chat workspaces drop it entirely. Discover, search and the hero CTA all
   lead back into marketing pages, and a conversation is not a place to sell
   from: /documents keeps its own wordmark in the sidebar as the way home, and
   /upload keeps a slim strip with the wordmark and nothing else. */

const NAV_LINKS = [
  { href: '/#features', label: '01 Discover' },
];

// No header at all: the workspace is the whole screen.
const HEADERLESS_ROUTES = ['/documents'];
// Only the wordmark, for a page that still needs a way home.
const SLIM_ROUTES = ['/upload'];

export default function Header() {
  const { pathname } = useLocation();

  if (HEADERLESS_ROUTES.some((route) => pathname.startsWith(route))) {
    return null;
  }

  const slim = SLIM_ROUTES.some((route) => pathname.startsWith(route));

  return (
    <header className={`main-header${slim ? ' main-header-chat' : ''}`}>
      <a href="/" className="logo-link">
        <span className="logo-name">ChronoMark</span>
      </a>

      {slim ? null : (
        <>
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="cell nav-link">
              {link.label}
            </a>
          ))}

          <div className="spacer" />

          <CommandPalette />

          <a href="/workspaces" className="cta">
            try now
            <ArrowUpRight />
          </a>
        </>
      )}
    </header>
  );
}
