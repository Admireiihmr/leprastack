import { Spinner } from "@/components/Spinner";

export default function Loading() {
  return (
    <main className="flex flex-1 items-center justify-center py-20">
      <Spinner className="h-8 w-8 text-teal-600" />
    </main>
  );
}
