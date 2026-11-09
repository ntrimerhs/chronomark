import '../styles/header.css';
import { ArrowUpRight } from 'lucide-react';
import CommandPalette from './CommandPalette';

/* The navigation, to the hero reference: the mark stays the supplied artwork,
   the name is set as spaced uppercase type beside it, and the sections are
   divided by hairlines rather than boxes. */

const NAV_LINKS = [
  { href: '/#features', label: '01 Discover' },
  { href: '/#about', label: '02 About' },
];

export default function Header() {
  return (
    <header className="main-header">
      <a href="/" className="logo-link">
        <span className="logo-name">ChronoMark</span>
      </a>

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
    </header>
  );
}
