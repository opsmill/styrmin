import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
  Button,
  Label,
  Input,
} from 'frontend';

// Base UI's Dialog.Root accepts `defaultOpen`, and the wrapper spreads props
// through, so the dialog renders in its open/composed state in a static card.
// DialogContent hardcodes a `bg-black/80` backdrop that fills the whole card in a
// static preview — neutralize it so the panel floats cleanly on the card.
const CleanBackdrop = () => (
  <style dangerouslySetInnerHTML={{ __html: '.bg-black\\/80{background:transparent !important}' }} />
);

export const Open = () => (
  <Dialog defaultOpen>
    <CleanBackdrop />
    <DialogTrigger asChild>
      <Button variant="outline">Delete cluster</Button>
    </DialogTrigger>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Delete cluster?</DialogTitle>
        <DialogDescription>
          This permanently removes production-eu and all of its deployments.
          This action cannot be undone.
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="ghost">Cancel</Button>
        </DialogClose>
        <Button variant="destructive">Delete</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
);

export const WithForm = () => (
  <Dialog defaultOpen>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>New environment</DialogTitle>
        <DialogDescription>
          Create an environment inside the selected cluster.
        </DialogDescription>
      </DialogHeader>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Label htmlFor="env-name">Name</Label>
          <Input id="env-name" placeholder="staging" />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Label htmlFor="env-ns">Namespace</Label>
          <Input id="env-ns" defaultValue="styrmin-staging" />
        </div>
      </div>
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="ghost">Cancel</Button>
        </DialogClose>
        <Button>Create</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
);
