import { useRouter } from "next/router";
import { useSearchParams } from "next/navigation";

/**
 * Returns a function that safely performs a shallow navigation
 * by using Next.js object-form router.push instead of string interpolation,
 * preventing XSS and URL redirect vulnerabilities from user-controlled params.
 */
export const useSafeRouterPush = () => {
  const router = useRouter();
  const searchParams = useSearchParams();

  return (params: URLSearchParams) => {
    const query: Record<string, string | string[] | undefined> = {};
    for (const key of Object.keys(router.query)) {
      if (!searchParams.has(key)) {
        query[key] = router.query[key];
      }
    }
    params.forEach((value, key) => {
      query[key] = value;
    });
    router.push({ pathname: router.pathname, query }, undefined, {
      shallow: true,
    });
  };
};
