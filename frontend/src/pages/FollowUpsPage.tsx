import FollowUps from "../components/FollowUps";
import { PageHeader } from "../components/ui";
import { useStation } from "../stations";

export default function FollowUpsPage() {
  const { station } = useStation();
  return (
    <>
      <PageHeader title="Follow-ups" subtitle={`What you raised with ${station ? `the cashier of ${station.name}` : "the stations' cashiers"}: each one stays open, with your notes, until it is sorted out.`} />
      <FollowUps title={station ? `Follow-ups, ${station.name}` : "Follow-ups, all stations"} />
    </>
  );
}
