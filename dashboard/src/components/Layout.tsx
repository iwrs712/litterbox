import { Link, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { LayoutDashboard, Server, Cat, FileCode, Database, Webhook } from 'lucide-react';
import { ThemeToggle } from '@/components/ThemeToggle';
import { LanguageToggle } from '@/components/LanguageToggle';
import { useApp } from '@/contexts/AppContext';

interface LayoutProps {
  children: React.ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const { t } = useApp();

  const navItems = [
    { path: '/', label: t.nav.dashboard, icon: LayoutDashboard },
    { path: '/sandboxes', label: t.nav.sandboxes, icon: Server },
    { path: '/templates', label: t.nav.templates, icon: FileCode },
    { path: '/pools', label: t.nav.pools, icon: Database },
    { path: '/webhooks', label: t.nav.webhooks, icon: Webhook },
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-16 items-center">
          <div className="mr-8 flex">
            <Link to="/" className="flex items-center space-x-2 group">
              <div className="relative">
                <Cat className="h-7 w-7 text-amber-500 group-hover:text-amber-600 transition-colors" />
                <div className="absolute -top-1 -right-1 w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              </div>
              <span className="font-bold text-lg tracking-tight">{t.header.title}</span>
            </Link>
          </div>
          <nav className="flex items-center space-x-2 flex-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={cn(
                    'flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center space-x-2 ml-auto">
            <LanguageToggle />
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container py-6 min-h-[calc(100vh-8rem)]">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t bg-background">
        <div className="container py-3">
          <p className="text-xs text-muted-foreground text-center">
            © {new Date().getFullYear()} Litterbox
          </p>
        </div>
      </footer>
    </div>
  );
}
