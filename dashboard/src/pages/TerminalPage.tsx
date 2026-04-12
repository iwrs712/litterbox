import { useParams } from 'react-router-dom';
import { Terminal } from '@/components/Terminal';

export function TerminalPage() {
  const { sandboxId } = useParams<{ sandboxId: string }>();

  if (!sandboxId) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#141414] text-[#888]">
        Sandbox ID not found
      </div>
    );
  }

  return (
    <div className="h-screen w-screen overflow-hidden" style={{ background: '#141414' }}>
      <Terminal sandboxId={sandboxId} />
    </div>
  );
}
