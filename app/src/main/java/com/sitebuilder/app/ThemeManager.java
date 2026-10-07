package com.sitebuilder.app;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;

public class ThemeManager {
    private static final String PREFS = "theme_prefs";
    private static final String KEY = "theme";

    public static final String THEME_DARK = "dark";
    public static final String THEME_BEIGE = "beige";
    public static final String THEME_LIGHT = "light";

    public static String getTheme(Context ctx) {
        SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return sp.getString(KEY, THEME_DARK);
    }

    public static void setTheme(Context ctx, String theme) {
        SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        sp.edit().putString(KEY, theme).apply();
    }

    public static int getThemeRes(String theme) {
        switch (theme) {
            case THEME_BEIGE: return R.style.Theme_SiteBuilder_Beige;
            case THEME_LIGHT: return R.style.Theme_SiteBuilder_Light;
            default: return R.style.Theme_SiteBuilder_Dark;
        }
    }

    public static void applyTheme(Activity activity) {
        String theme = getTheme(activity);
        activity.setTheme(getThemeRes(theme));
    }
}
