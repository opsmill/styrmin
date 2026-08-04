import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
  Button,
} from 'frontend';

export const Default = () => (
  <Card className="w-[360px]">
    <CardHeader>
      <CardTitle>Production cluster</CardTitle>
      <CardDescription>eu-west-1 · 12 active deployments</CardDescription>
    </CardHeader>
    <CardContent>
      All components are healthy and reconciled to the latest driver version.
    </CardContent>
    <CardFooter className="gap-2">
      <Button>View deployments</Button>
      <Button variant="outline">Settings</Button>
    </CardFooter>
  </Card>
);
