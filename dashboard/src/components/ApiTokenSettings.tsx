import { useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { useApp } from '@/contexts/AppContext';

export function ApiTokenSettings() {
  const { t, apiToken, setApiToken, clearApiToken, hasApiToken } = useApp();
  const [open, setOpen] = useState(false);
  const [draftToken, setDraftToken] = useState(apiToken);

  useEffect(() => {
    if (open) {
      setDraftToken(apiToken);
    }
  }, [open, apiToken]);

  const handleSave = () => {
    setApiToken(draftToken);
    setOpen(false);
  };

  const handleClear = () => {
    clearApiToken();
    setDraftToken('');
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="relative h-9 w-9">
          <KeyRound className="h-[1.1rem] w-[1.1rem]" />
          {hasApiToken ? (
            <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-emerald-500" />
          ) : null}
          <span className="sr-only">{t.auth.openButton}</span>
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t.auth.dialogTitle}</DialogTitle>
          <DialogDescription>{t.auth.dialogDescription}</DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="api-token">{t.auth.tokenLabel}</Label>
          <Input
            id="api-token"
            type="password"
            autoComplete="off"
            placeholder={t.auth.tokenPlaceholder}
            value={draftToken}
            onChange={(event) => setDraftToken(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {hasApiToken ? t.auth.configured : t.auth.notConfigured}
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClear}>
            {t.auth.clearToken}
          </Button>
          <Button onClick={handleSave}>{t.auth.saveToken}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
