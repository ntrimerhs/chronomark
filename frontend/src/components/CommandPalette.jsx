import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Command, Upload, Search, Settings, Home, FileText } from 'lucide-react';
import '../styles/command-palette.css';

const CommandPalette = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const commands = [
    {
      id: 'home',
      label: 'Home',
      description: 'Go to the home page',
      icon: Home,
      action: () => {
        window.location.href = '/';
        setIsOpen(false);
      },
    },
    {
      id: 'upload',
      label: 'Upload Video',
      description: 'Upload and analyze a video file',
      icon: Upload,
      action: () => {
        window.location.href = '/upload';
        setIsOpen(false);
      },
    },
    {
      id: 'documents',
      label: 'Upload Documents',
      description: 'Upload and analyze a PDF, PowerPoint or Word file',
      icon: FileText,
      action: () => {
        window.location.href = '/documents';
        setIsOpen(false);
      },
    },
    {
      id: 'search',
      label: 'Search Videos',
      description: 'Search through your uploaded videos',
      icon: Search,
      action: () => {
        window.location.href = '/upload';
        setIsOpen(false);
      },
    },
    {
      id: 'settings',
      label: 'Settings',
      description: 'Configure app preferences',
      icon: Settings,
      action: () => {
        window.location.href = '/settings';
        setIsOpen(false);
      },
    },
  ];

  const filteredCommands = commands.filter(cmd =>
    cmd.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
    cmd.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen(!isOpen);
        setSearchQuery('');
      }
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
        setSearchQuery('');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  return (
    <>
      <button
        className="cell cell-search"
        type="button"
        aria-label="Search"
        onClick={() => {
          setIsOpen(!isOpen);
          setSearchQuery('');
        }}
        title="Press Cmd+K or Ctrl+K"
      >
        <Search size={14} />
        <span>search</span>
      </button>

      {isOpen && createPortal(
        <>
          <div className="command-palette-overlay" onClick={() => setIsOpen(false)} />
          <div className="command-palette-modal">
            <div className="command-palette-header">
              <Command size={18} />
              <input
                type="text"
                placeholder="Search commands..."
                className="command-palette-input"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                autoFocus
              />
            </div>

            <div className="command-palette-list">
              {filteredCommands.length > 0 ? (
                filteredCommands.map((cmd) => {
                  const IconComponent = cmd.icon;
                  return (
                    <button
                      key={cmd.id}
                      className="command-palette-item"
                      onClick={cmd.action}
                    >
                      <IconComponent size={16} className="command-palette-item-icon" />
                      <div className="command-palette-item-content">
                        <div className="command-palette-item-label">{cmd.label}</div>
                        <div className="command-palette-item-description">
                          {cmd.description}
                        </div>
                      </div>
                    </button>
                  );
                })
              ) : (
                <div className="command-palette-empty">
                  No commands found for "{searchQuery}"
                </div>
              )}
            </div>

            <div className="command-palette-footer">
              <span className="command-palette-hint">
                Press <kbd>ESC</kbd> to close
              </span>
            </div>
          </div>
        </>,
        document.body
      )}
    </>
  );
};

export default CommandPalette;
