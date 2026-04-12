import test from "node:test";
import assert from "node:assert/strict";

import { parseLaunchParams, shouldAutoSearch } from "./launchParams.ts";

test("parseLaunchParams は full_path と q と index_depth を取り出す", () => {
  const params = parseLaunchParams("?full_path=%2Ftmp%2Fdocs&q=%E8%A6%8B%E7%A9%8D&index_depth=2");

  assert.deepEqual(params, {
    q: "見積",
    fullPath: "/tmp/docs",
    indexDepth: "2",
  });
});

test("parseLaunchParams は index_depth が無いとき既定値 5 を使う", () => {
  const params = parseLaunchParams("?full_path=%2Ftmp%2Fdocs&q=keyword");

  assert.equal(params.indexDepth, "5");
});

test("parseLaunchParams は不正な index_depth を既定値 5 に丸める", () => {
  const params = parseLaunchParams("?full_path=%2Ftmp%2Fdocs&q=keyword&index_depth=-1");

  assert.equal(params.indexDepth, "5");
});

test("shouldAutoSearch は q と fullPath がそろったときだけ true を返す", () => {
  assert.equal(
    shouldAutoSearch({
      q: "見積",
      fullPath: "/tmp/docs",
      indexDepth: "5",
    }),
    true,
  );

  assert.equal(
    shouldAutoSearch({
      q: "",
      fullPath: "/tmp/docs",
      indexDepth: "5",
    }),
    false,
  );
});
