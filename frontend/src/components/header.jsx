import '../styles/header.css';
import { ArrowUpRight } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import CommandPalette from './CommandPalette';

/* The navigation, to the hero reference: the mark stays the supplied artwork,
   the name is set as spaced uppercase type beside it, and the sections are
   divided by hairlines rather than boxes.

   The chat workspaces keep only the logo. Discover, search and the hero CTA all
   lead back into marketing pages, and inside a conversation the one thing the
   header should still do is take you home. */

const NAV_LINKS = [
  { href: '/#features', label: '01 Discover' },
];

const CHAT_ROUTES = ['/upload', '/documents'];

export default function Header() {
  const { pathname } = useLocation();
  const chatMode = CHAT_ROUTES.some((route) => pathname.startsWith(route));

  return (
    <header className={`main-header${chatMode ? ' main-header-chat' : ''}`}>
      <a href="/" className="logo-link">
        <span className="logo-name">ChronoMark</span>
      </a>

      {chatMode ? null : (
        <>
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="cell nav-link">
              {link.label}
            </a>
          ))}

          <div className="spacer" />

          <CommandPalette />

          <a href="/upload" className="cta">
            try now
            <ArrowUpRight />
          </a>
        </>
      )}
    </header>
  );
}
